"""AAIP discovery protocol module."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin
import httpx
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import Agent, AgentDiscoveryProfile
from registry import generate_aaip_agent_id

DEFAULT_MANIFEST_PATHS = [
    "/.well-known/aaip-agent.json",
    "/.well-known/arpp-agent.json",
    "/aaip/agent.json",
    "/arpp/agent.json",
]

class DiscoveryManifest(BaseModel):
    agent_name:   str = Field(..., min_length=1, max_length=200)
    owner:        str = Field(..., min_length=1, max_length=200)
    version:      str = Field(default="1.0.0", max_length=50)
    description:  str = Field(default="", max_length=2000)
    endpoint:     HttpUrl
    domains:      list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    tools:        list[str] = Field(default_factory=list)
    public_key:   Optional[str] = Field(default=None, max_length=5000)
    tags:         list[str] = Field(default_factory=list)
    framework:    Optional[str] = Field(default=None, max_length=100)
    evaluation:   dict = Field(default_factory=dict)
    metadata:     dict = Field(default_factory=dict)

    @field_validator("domains", mode="before")
    @classmethod
    def open_domains(cls, v: list[str]) -> list[str]:
        if not v:
            return v
        return [d.lower().strip().replace(" ", "_") for d in v if d]

    def primary_domain(self) -> str:
        caps = self.capabilities or self.domains
        return caps[0] if caps else "general"

class DiscoveryRegisterRequest(BaseModel):
    manifest_url: Optional[HttpUrl] = None
    manifest:     Optional[DiscoveryManifest] = None
    path_hints:   list[str] = Field(default_factory=list)

class DiscoveryCrawlResponse(BaseModel):
    aaip_agent_id:    str
    discovery_status: str
    manifest_url:     str
    crawl_status:     str
    manifest:         dict
    created_at:       datetime
    updated_at:       datetime

async def fetch_manifest(manifest_url: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(manifest_url)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Manifest must be a JSON object")
        return data

async def discover_from_base_url(base_url: str, path_hints: Optional[list[str]] = None) -> tuple[str, dict]:
    errors = []
    paths: list[str] = []
    for item in (path_hints or []):
        if item and item not in paths:
            paths.append(item if item.startswith("/") else f"/{item}")
    for item in DEFAULT_MANIFEST_PATHS:
        if item not in paths:
            paths.append(item)
    for path in paths:
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        try:
            return url, await fetch_manifest(url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise ValueError("No AAIP manifest found. Tried: " + " | ".join(errors))

async def upsert_discovered_agent(db: AsyncSession, manifest: DiscoveryManifest, manifest_url: str,
                                   discovery_status: str = "active", crawl_status: str = "success") -> DiscoveryCrawlResponse:
    primary_domain = manifest.primary_domain()
    all_domains = list(set((manifest.domains or []) + (manifest.capabilities or []))) or [primary_domain]

    result = await db.execute(select(AgentDiscoveryProfile).where(AgentDiscoveryProfile.manifest_url == str(manifest_url)))
    profile = result.scalar_one_or_none()

    if profile:
        agent = await db.get(Agent, profile.agent_id)
        if agent:
            agent.company_name = manifest.owner
            agent.agent_name   = manifest.agent_name
            agent.domain       = primary_domain
            agent.version      = manifest.version
    else:
        result = await db.execute(select(Agent).where(Agent.company_name == manifest.owner, Agent.agent_name == manifest.agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            agent = Agent(aaip_agent_id=generate_aaip_agent_id(manifest.owner, manifest.agent_name),
                          company_name=manifest.owner, agent_name=manifest.agent_name,
                          domain=primary_domain, version=manifest.version)
            db.add(agent)
            await db.flush()
        profile = AgentDiscoveryProfile(agent_id=agent.id, manifest_url=str(manifest_url))
        db.add(profile)

    profile.endpoint_url        = str(manifest.endpoint)
    profile.description         = manifest.description
    profile.domains             = all_domains
    profile.tools               = manifest.tools
    profile.public_key          = manifest.public_key
    profile.tags                = manifest.tags
    profile.metadata_json       = manifest.metadata
    profile.evaluation_snapshot = manifest.evaluation
    profile.manifest_json       = manifest.model_dump(mode="json")
    profile.discovery_status    = discovery_status
    profile.crawl_status        = crawl_status
    profile.last_seen_at        = datetime.utcnow()
    profile.updated_at          = datetime.utcnow()

    await db.commit()
    await db.refresh(profile)
    await db.refresh(agent)
    return DiscoveryCrawlResponse(aaip_agent_id=agent.aaip_agent_id, discovery_status=profile.discovery_status,
                                   manifest_url=profile.manifest_url, crawl_status=profile.crawl_status,
                                   manifest=profile.manifest_json, created_at=profile.created_at, updated_at=profile.updated_at)

async def crawl_and_register_agent(db: AsyncSession, manifest_url: Optional[str] = None,
                                    base_url: Optional[str] = None, path_hints: Optional[list[str]] = None) -> DiscoveryCrawlResponse:
    if manifest_url:
        raw = await fetch_manifest(manifest_url)
    elif base_url:
        manifest_url, raw = await discover_from_base_url(base_url, path_hints=path_hints)
    else:
        raise ValueError("manifest_url or base_url is required")
    return await upsert_discovered_agent(db=db, manifest=DiscoveryManifest.model_validate(raw), manifest_url=str(manifest_url))

async def get_discovery_profile(db: AsyncSession, aaip_agent_id: str) -> Optional[dict]:
    result = await db.execute(select(AgentDiscoveryProfile, Agent).join(Agent, Agent.id == AgentDiscoveryProfile.agent_id).where(Agent.aaip_agent_id == aaip_agent_id))
    row = result.first()
    if not row:
        return None
    profile, agent = row
    return {"aaip_agent_id": agent.aaip_agent_id, "agent_name": agent.agent_name, "owner": agent.company_name,
            "version": agent.version, "manifest_url": profile.manifest_url, "endpoint_url": profile.endpoint_url,
            "description": profile.description, "domains": profile.domains, "tools": profile.tools,
            "tags": profile.tags, "public_key": profile.public_key, "evaluation_snapshot": profile.evaluation_snapshot,
            "discovery_status": profile.discovery_status, "crawl_status": profile.crawl_status,
            "last_seen_at": profile.last_seen_at.isoformat() if profile.last_seen_at else None,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None, "manifest": profile.manifest_json}

async def list_discoverable_agents(db: AsyncSession, domain: Optional[str] = None, tag: Optional[str] = None, limit: int = 50) -> list[dict]:
    rows = (await db.execute(select(AgentDiscoveryProfile, Agent).join(Agent, Agent.id == AgentDiscoveryProfile.agent_id)
            .where(AgentDiscoveryProfile.discovery_status == "active").order_by(AgentDiscoveryProfile.updated_at.desc()).limit(limit))).all()
    items = []
    for profile, agent in rows:
        if domain and domain not in (profile.domains or []):
            continue
        if tag and tag not in (profile.tags or []):
            continue
        items.append({"aaip_agent_id": agent.aaip_agent_id, "agent_name": agent.agent_name, "owner": agent.company_name,
                      "primary_domain": agent.domain, "domains": profile.domains, "description": profile.description,
                      "endpoint_url": profile.endpoint_url, "manifest_url": profile.manifest_url, "tags": profile.tags,
                      "tools": profile.tools, "evaluation_snapshot": profile.evaluation_snapshot,
                      "updated_at": profile.updated_at.isoformat() if profile.updated_at else None})
    return items
