
import csv
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Preformatted,
    Table,
    TableStyle,
)

# Optional AI and research integrations
try:
    from google import genai
except ImportError:
    genai = None

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("marketing_campaign")

APP_NAME = "Agentic AI Marketing Campaign System"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./marketing_campaigns.db",
)

engine_options = {}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

gemini_client = None
if GEMINI_API_KEY and genai is not None:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialized.")
    except Exception:
        logger.exception("Gemini initialization failed.")


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String(255), nullable=False)
    target_audience = Column(Text, nullable=False)
    campaign_goal = Column(String(255), nullable=False)
    budget = Column(Float, nullable=False, default=0)
    approval_status = Column(
        String(50),
        nullable=False,
        default="pending",
    )
    review_feedback = Column(Text, nullable=True)
    results = Column("results_json", Text, nullable=False, default="{}")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------

class CampaignRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=255)
    target_audience: str = Field(min_length=1)
    campaign_goal: str = Field(
        default="Increase brand awareness",
        max_length=255,
    )
    budget: float = Field(default=10000, ge=0)
    brand_name: str = "Your Brand"
    tone: str = "Professional"
    platforms: list[str] = Field(
        default_factory=lambda: ["LinkedIn", "Email", "Instagram"]
    )
    additional_requirements: str = ""


class ApprovalRequest(BaseModel):
    status: str
    feedback: Optional[str] = None


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def parse_json(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {} if default is None else default


def campaign_to_dict(campaign: Campaign) -> dict:
    created_at = campaign.created_at
    return {
        "id": campaign.id,
        "product_name": campaign.product_name,
        "target_audience": campaign.target_audience,
        "campaign_goal": campaign.campaign_goal,
        "budget": campaign.budget,
        "approval_status": campaign.approval_status,
        "review_feedback": campaign.review_feedback,
        "results": parse_json(campaign.results, {}),
        "created_at": (
            created_at.isoformat() if created_at else None
        ),
    }


def clean_text(value: Any) -> str:
    """Convert a value to safe plain text for PDF output."""
    text = str(value if value is not None else "")
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def generate_ai_text(prompt: str) -> Optional[str]:
    """Return Gemini output, or None if AI is temporarily unavailable."""
    if gemini_client is None:
        return None

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        text = getattr(response, "text", None)
        return text.strip() if text else None
    except Exception as exc:
        logger.warning("Gemini request failed: %s", exc)
        return None


def generate_agent_result(
    agent_name: str,
    prompt: str,
    fallback: dict,
) -> dict:
    """
    Ask Gemini for a JSON object.
    If the API is unavailable or returns invalid JSON, use fallback data.
    """
    full_prompt = f"""
You are the {agent_name} in a multi-agent marketing campaign application.

Follow the user's requirements. Do not invent research sources, customer
data, performance results, or verified product claims.

Return only one valid JSON object. Do not use Markdown fences.

Task:
{prompt}

Required JSON structure:
{json.dumps(fallback, ensure_ascii=False)}
"""
    response_text = generate_ai_text(full_prompt)

    if response_text:
        try:
            cleaned = re.sub(
                r"^\s*```(?:json)?\s*|\s*```\s*$",
                "",
                response_text,
                flags=re.IGNORECASE,
            )
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                parsed["agent_name"] = agent_name
                parsed["generated_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                parsed["generation_mode"] = "AI"
                return parsed
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "%s returned invalid JSON; using fallback.",
                agent_name,
            )

    result = dict(fallback)
    result["agent_name"] = agent_name
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["generation_mode"] = (
        "Fallback" if GEMINI_API_KEY else "Fallback - AI key not configured"
    )
    return result


# ---------------------------------------------------------
# RESEARCH TOOL
# ---------------------------------------------------------

def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web for supporting context.
    Results contain titles, URLs and snippets when DDGS is available.
    """
    if DDGS is None:
        return [{
            "title": "Live research unavailable",
            "url": "",
            "snippet": (
                "Install the ddgs package and ensure internet access "
                "to enable live web research."
            ),
        }]

    try:
        results = []
        with DDGS() as search_client:
            for item in search_client.text(
                query,
                max_results=max_results,
            ):
                results.append({
                    "title": item.get("title", "Untitled"),
                    "url": item.get("href", item.get("url", "")),
                    "snippet": item.get("body", ""),
                })
        return results
    except Exception as exc:
        logger.warning("Web research failed: %s", exc)
        return [{
            "title": "Live research temporarily unavailable",
            "url": "",
            "snippet": (
                "The search service did not return results. "
                "Do not treat fallback suggestions as verified research."
            ),
        }]


# ---------------------------------------------------------
# SIX SPECIALIZED AGENTS
# ---------------------------------------------------------

def run_requirement_analysis(request: CampaignRequest) -> dict:
    fallback = {
        "product_summary": (
            f"{request.product_name} campaign for "
            f"{request.target_audience}."
        ),
        "campaign_goal": request.campaign_goal,
        "primary_objectives": [
            "Increase awareness",
            "Encourage qualified engagement",
            "Measure campaign outcomes",
        ],
        "key_requirements": [
            "Use the requested platforms",
            "Maintain the selected brand tone",
            "Require human approval before publication",
        ],
        "assumptions": [
            "Budget is expressed in INR.",
            "Performance targets are planning estimates, not guarantees.",
        ],
        "missing_information": [
            "Brand guidelines",
            "Verified product specifications",
            "Historical campaign results",
        ],
    }

    prompt = f"""
Analyze the campaign requirements.

Product: {request.product_name}
Brand: {request.brand_name}
Audience: {request.target_audience}
Goal: {request.campaign_goal}
Budget in INR: {request.budget}
Tone: {request.tone}
Platforms: {request.platforms}
Additional requirements: {request.additional_requirements}

Identify objectives, requirements, assumptions, and missing information.
Never invent product facts.
"""
    return generate_agent_result(
        "Marketing Requirement Analysis Agent",
        prompt,
        fallback,
    )


def run_research(request: CampaignRequest) -> dict:
    query = (
        f"{request.product_name} market trends "
        f"{request.target_audience} marketing"
    )
    sources = search_web(query)

    fallback = {
        "research_query": query,
        "audience_segments": [
            {
                "segment": request.target_audience,
                "needs": [
                    "Understand the product's value",
                    "Compare relevant options",
                    "Find trustworthy product information",
                ],
                "message_angle": (
                    "Explain practical benefits using verified details."
                ),
                "recommended_channels": request.platforms,
            }
        ],
        "competitor_research": [
            {
                "finding": (
                    "Competitor positioning needs validation against "
                    "the sources listed below."
                ),
                "limitation": (
                    "Do not infer market share, prices, or competitor "
                    "performance without evidence."
                ),
            }
        ],
        "market_trends": [
            "Use audience-specific messaging.",
            "Test different content formats.",
            "Measure results before reallocating budget.",
        ],
        "sources": sources,
        "research_limitations": [
            "Search snippets may be incomplete or outdated.",
            "Verify sources before relying on a claim.",
        ],
    }

    prompt = f"""
Research the target audience and competitors for this campaign.

Product: {request.product_name}
Audience: {request.target_audience}
Goal: {request.campaign_goal}
Platforms: {request.platforms}

Use the supplied search results as the only source material.
Do not claim you verified anything not present in the results.
Do not invent statistics, competitor names, or market share.

Search results:
{json.dumps(sources, ensure_ascii=False)}

Provide audience segments, needs, possible competitor insights,
market trends, and research limitations.
"""
    return generate_agent_result(
        "Audience and Competitor Research Agent",
        prompt,
        fallback,
    )


def run_campaign_strategy(
    request: CampaignRequest,
    requirement_analysis: dict,
    research: dict,
) -> dict:
    budget = float(request.budget)
    allocation = {
        "Content creation": round(budget * 0.25, 2),
        "Paid promotion": round(budget * 0.40, 2),
        "Email and outreach": round(budget * 0.15, 2),
        "Testing and optimization": round(budget * 0.10, 2),
        "Contingency": round(budget * 0.10, 2),
    }

    fallback = {
        "positioning": (
            f"Position {request.product_name} around clear, "
            "audience-relevant benefits supported by verified facts."
        ),
        "objectives": [
            request.campaign_goal,
            "Generate relevant engagement",
            "Track conversions and campaign cost",
        ],
        "budget_allocation_inr": allocation,
        "timeline": [
            {
                "period": "Days 1-5",
                "activities": "Finalize audience, claims, and campaign assets.",
            },
            {
                "period": "Days 6-12",
                "activities": "Launch approved content and test messaging.",
            },
            {
                "period": "Days 13-21",
                "activities": "Review performance and adjust content.",
            },
            {
                "period": "Days 22-30",
                "activities": "Evaluate results and prepare a report.",
            },
        ],
        "kpis": [
            {
                "name": "Impressions",
                "definition": "Number of times content is displayed.",
                "target": "Set after baseline and budget are reviewed.",
            },
            {
                "name": "Click-through rate",
                "definition": "Clicks divided by impressions, multiplied by 100.",
                "target": "Planning target; validate against baseline.",
            },
            {
                "name": "Conversion rate",
                "definition": "Conversions divided by clicks, multiplied by 100.",
                "target": "Set based on the conversion definition and baseline.",
            },
            {
                "name": "Cost per conversion",
                "definition": "Spend divided by conversions.",
                "target": "Compare with the business's acceptable acquisition cost.",
            },
        ],
        "approval_gate": (
            "No content may be published until a human reviewer approves it."
        ),
    }

    prompt = f"""
Create a practical 30-day marketing strategy.

Product: {request.product_name}
Audience: {request.target_audience}
Goal: {request.campaign_goal}
Budget INR: {budget}
Platforms: {request.platforms}
Tone: {request.tone}

Requirements analysis:
{json.dumps(requirement_analysis, ensure_ascii=False)}

Audience research:
{json.dumps(research, ensure_ascii=False)}

Allocate the entire budget in INR. Include timeline, KPIs, positioning,
and an explicit human approval gate. Clearly label targets as estimates.
Do not claim that projected performance is actual performance.
"""
    return generate_agent_result(
        "Campaign Strategy Agent",
        prompt,
        fallback,
    )


def run_content_generation(
    request: CampaignRequest,
    strategy: dict,
) -> dict:
    fallback = {
        "platform_content": [
            {
                "platform": platform,
                "format": (
                    "Professional post"
                    if platform.lower() == "linkedin"
                    else "Email" if platform.lower() == "email"
                    else "Caption"
                ),
                "headline": f"Discover {request.product_name}",
                "content": (
                    f"Looking for a practical way to explore "
                    f"{request.product_name}? Learn about its features "
                    "and benefits, and decide whether it fits your needs. "
                    "Check verified product details before making a decision."
                ),
                "call_to_action": "Learn more",
                "status": "Draft - requires human review",
            }
            for platform in request.platforms
        ],
        "content_calendar": [
            {
                "day": day,
                "platform": request.platforms[(day - 1) % len(request.platforms)],
                "content_type": [
                    "Introduction",
                    "Educational content",
                    "Feature spotlight",
                    "Frequently asked questions",
                    "Engagement prompt",
                ][(day - 1) % 5],
                "topic": f"{request.product_name}: campaign topic {day}",
                "goal": request.campaign_goal,
                "status": "Draft - requires human review",
            }
            for day in range(1, 31)
        ],
        "content_notes": [
            "Replace generic copy with verified product details.",
            "Do not publish automatically.",
            "All drafts require human approval.",
        ],
    }

    prompt = f"""
Generate platform-specific marketing content and a complete 30-day
content calendar.

Product: {request.product_name}
Brand: {request.brand_name}
Audience: {request.target_audience}
Goal: {request.campaign_goal}
Tone: {request.tone}
Platforms: {request.platforms}
Additional requirements: {request.additional_requirements}

Strategy:
{json.dumps(strategy, ensure_ascii=False)}

Include content for every requested platform and exactly 30 calendar entries.
Each entry should include day, platform, content type, topic, goal, and status.
Do not invent product specifications, certifications, guarantees, or testimonials.
All content must be drafts awaiting human approval.
"""
    return generate_agent_result(
        "Content Generation Agent",
        prompt,
        fallback,
    )


def run_content_review(
    request: CampaignRequest,
    generated_content: dict,
) -> dict:
    fallback = {
        "overall_status": "Needs human review",
        "automated_checks": [
            {
                "check": "Unsupported claims",
                "status": "Manual verification required",
                "details": (
                    "Check all product specifications, results, guarantees, "
                    "and comparisons against reliable evidence."
                ),
            },
            {
                "check": "Brand tone",
                "status": "Draft review required",
                "details": f"Requested tone: {request.tone}.",
            },
            {
                "check": "Platform suitability",
                "status": "Draft review required",
                "details": "Review format, length, and platform requirements.",
            },
        ],
        "flagged_claims": [],
        "required_actions": [
            "Verify product claims.",
            "Check brand guidelines.",
            "Obtain explicit human approval before publication.",
        ],
        "publication_allowed": False,
    }

    prompt = f"""
Review the following marketing content for brand compliance and unsupported
claims. Do not treat this automated review as proof that claims are true.

Product: {request.product_name}
Brand: {request.brand_name}
Tone: {request.tone}

Content:
{json.dumps(generated_content, ensure_ascii=False)}

Flag specific unsupported claims where possible. Include checks for tone,
platform suitability, misleading claims, and required human review.
Set publication_allowed to false because this system never auto-publishes.
"""
    result = generate_agent_result(
        "Content Review and Brand Compliance Agent",
        prompt,
        fallback,
    )
    result["publication_allowed"] = False
    return result


def run_analytics_plan(
    request: CampaignRequest,
    strategy: dict,
) -> dict:
    fallback = {
        "measurement_type": "Projected plan; not actual performance",
        "budget_inr": request.budget,
        "metrics_to_track": [
            "Impressions",
            "Clicks",
            "Engagements",
            "Conversions",
            "Spend",
            "CTR",
            "Engagement rate",
            "Conversion rate",
            "Cost per conversion",
        ],
        "formulas": {
            "CTR": "clicks / impressions * 100",
            "Engagement rate": "engagements / impressions * 100",
            "Conversion rate": "conversions / clicks * 100",
            "Cost per conversion": "spend / conversions",
        },
        "reporting_frequency": "Weekly and at the end of 30 days",
        "data_quality_checks": [
            "Confirm that uploaded CSV values are real or sample data.",
            "Avoid division by zero.",
            "Validate that counts and spending are non-negative.",
        ],
    }

    prompt = f"""
Create an analytics measurement plan, not a fabricated performance report.

Product: {request.product_name}
Budget INR: {request.budget}
Strategy:
{json.dumps(strategy, ensure_ascii=False)}

Include metric definitions, formulas, reporting frequency, and data-quality
checks. Actual results must come from uploaded performance data only.
"""
    return generate_agent_result(
        "Campaign Analytics Agent",
        prompt,
        fallback,
    )


# ---------------------------------------------------------
# CAMPAIGN ORCHESTRATION
# ---------------------------------------------------------

def execute_campaign(request: CampaignRequest) -> dict:
    """
    Execute all six agents in order and store their structured results.
    The human approval step is separate.
    """
    logger.info("Starting campaign workflow for %s", request.product_name)

    requirement_analysis = run_requirement_analysis(request)
    research = run_research(request)
    strategy = run_campaign_strategy(
        request,
        requirement_analysis,
        research,
    )
    generated_content = run_content_generation(request, strategy)
    content_review = run_content_review(request, generated_content)
    analytics_plan = run_analytics_plan(request, strategy)

    results = {
        "workflow_state": "awaiting_human_approval",
        "agents_completed": 6,
        "requirement_analysis": requirement_analysis,
        "audience_competitor_research": research,
        "campaign_strategy": strategy,
        "generated_content_and_calendar": generated_content,
        "content_review": content_review,
        "analytics_plan": analytics_plan,
        "human_approval_required": True,
        "publication_enabled": False,
    }

    db = SessionLocal()
    try:
        campaign = Campaign(
            product_name=request.product_name.strip(),
            target_audience=request.target_audience.strip(),
            campaign_goal=request.campaign_goal.strip(),
            budget=float(request.budget),
            approval_status="pending",
            review_feedback=None,
            results=json.dumps(results, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        response = campaign_to_dict(campaign)
        response["message"] = "Campaign generated; human approval required."
        response["agents_completed"] = 6
        return response
    except Exception:
        db.rollback()
        logger.exception("Could not save campaign.")
        raise HTTPException(
            status_code=500,
            detail="Campaign was generated but could not be saved.",
        )
    finally:
        db.close()


# ---------------------------------------------------------
# FASTAPI APP AND CORS
# ---------------------------------------------------------

app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    description=(
        "Multi-agent marketing campaign generation, human approval, "
        "analytics, and export APIs."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": APP_NAME,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "database": "configured",
        "gemini_configured": bool(gemini_client),
        "research_available": DDGS is not None,
        "agents": 6,
    }


# ---------------------------------------------------------
# CAMPAIGN ENDPOINTS
# ---------------------------------------------------------

@app.post("/run-campaign")
def run_campaign(request: CampaignRequest):
    return execute_campaign(request)


@app.post("/create-campaign")
def create_campaign(request: CampaignRequest):
    return execute_campaign(request)


@app.post("/generate-content")
def generate_content(request: CampaignRequest):
    generated = run_content_generation(request, {})
    return {
        "product_name": request.product_name,
        "generated_content_and_calendar": generated,
        "human_approval_required": True,
        "publication_enabled": False,
    }


@app.get("/campaigns")
def get_campaigns():
    db = SessionLocal()
    try:
        campaigns = (
            db.query(Campaign)
            .order_by(Campaign.id.desc())
            .all()
        )
        return [campaign_to_dict(item) for item in campaigns]
    finally:
        db.close()


@app.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int):
    db = SessionLocal()
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id)
            .first()
        )
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail="Campaign not found.",
            )
        return campaign_to_dict(campaign)
    finally:
        db.close()


@app.post("/campaigns/{campaign_id}/approval")
def update_campaign_approval(
    campaign_id: int,
    request: ApprovalRequest,
):
    status = request.status.strip().lower()
    allowed_statuses = {"approved", "rejected", "pending"}

    if status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Status must be approved, rejected, or pending.",
        )

    db = SessionLocal()
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id)
            .first()
        )
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail="Campaign not found.",
            )

        campaign.approval_status = status
        campaign.review_feedback = request.feedback
        db.commit()
        db.refresh(campaign)

        response = campaign_to_dict(campaign)
        response["message"] = f"Campaign status updated to {status}."
        return response
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Approval update failed.")
        raise HTTPException(
            status_code=500,
            detail="Could not update campaign approval.",
        )
    finally:
        db.close()


# ---------------------------------------------------------
# CAMPAIGN CSV EXPORT
# ---------------------------------------------------------

@app.get("/campaigns/{campaign_id}/export.csv")
def export_campaign_csv(campaign_id: int):
    db = SessionLocal()
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id)
            .first()
        )
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail="Campaign not found.",
            )

        data = campaign_to_dict(campaign)
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        writer.writerow(["Field", "Value"])
        writer.writerow(["Campaign ID", data["id"]])
        writer.writerow(["Product", data["product_name"]])
        writer.writerow(["Target Audience", data["target_audience"]])
        writer.writerow(["Campaign Goal", data["campaign_goal"]])
        writer.writerow(["Budget INR", data["budget"]])
        writer.writerow(["Approval Status", data["approval_status"]])
        writer.writerow(["Review Feedback", data["review_feedback"] or ""])
        writer.writerow(["Created At", data["created_at"] or ""])
        writer.writerow([
            "Agent Results",
            json.dumps(data["results"], ensure_ascii=False),
        ])

        csv_bytes = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
        return StreamingResponse(
            csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition":
                    f'attachment; filename="campaign_{campaign_id}.csv"'
            },
        )
    finally:
        db.close()


# ---------------------------------------------------------
# CAMPAIGN PDF EXPORT
# ---------------------------------------------------------

@app.get("/campaigns/{campaign_id}/export.pdf")
def export_campaign_pdf(campaign_id: int):
    db = SessionLocal()
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id)
            .first()
        )
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail="Campaign not found.",
            )

        data = campaign_to_dict(campaign)
        results = data.get("results", {})

        buffer = io.BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=0.6 * inch,
            leftMargin=0.6 * inch,
            topMargin=0.6 * inch,
            bottomMargin=0.6 * inch,
        )

        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(
            "Agentic AI Marketing Campaign Report",
            styles["Title"],
        ))
        story.append(Spacer(1, 12))
        story.append(Paragraph("Campaign Overview", styles["Heading1"]))

        overview_rows = [
            ["Field", "Value"],
            ["Campaign ID", str(data["id"])],
            ["Product", str(data["product_name"])],
            ["Target Audience", str(data["target_audience"])],
            ["Campaign Goal", str(data["campaign_goal"])],
            ["Budget (INR)", str(data["budget"])],
            ["Approval Status", str(data["approval_status"])],
            ["Created At", str(data["created_at"] or "Not available")],
            ["Review Feedback", str(data["review_feedback"] or "None")],
        ]

        safe_rows = [
            [clean_text(cell) for cell in row]
            for row in overview_rows
        ]

        overview_table = Table(
            safe_rows,
            colWidths=[1.55 * inch, 4.9 * inch],
            repeatRows=1,
        )
        overview_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(overview_table)
        story.append(Spacer(1, 18))

        story.append(Paragraph("Six-Agent Results", styles["Heading1"]))

        agent_sections = [
            ("1. Marketing Requirement Analysis", "requirement_analysis"),
            ("2. Audience and Competitor Research", "audience_competitor_research"),
            ("3. Campaign Strategy", "campaign_strategy"),
            ("4. Content Generation and Calendar", "generated_content_and_calendar"),
            ("5. Content Review and Brand Compliance", "content_review"),
            ("6. Campaign Analytics Plan", "analytics_plan"),
        ]

        for heading, key in agent_sections:
            story.append(Paragraph(clean_text(heading), styles["Heading2"]))
            agent_result = results.get(key, {})
            serialized = json.dumps(
                agent_result,
                ensure_ascii=False,
                indent=2,
            )
            serialized = clean_text(serialized)

            # Keep long agent results readable and avoid one oversized paragraph.
            story.append(Preformatted(
                serialized,
                styles["Code"],
                maxLineLength=85,
            ))
            story.append(Spacer(1, 12))

        story.append(Spacer(1, 12))
        story.append(Paragraph(
            "Human approval is required before campaign content can be used. "
            "This application does not publish content externally. "
            "Analytics results should be treated as actual only when they "
            "come from verified performance data.",
            styles["Italic"],
        ))

        document.build(story)
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'attachment; filename="campaign_{campaign_id}.pdf"'
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF export failed.")
        raise HTTPException(
            status_code=500,
            detail=f"Could not generate PDF: {str(exc)}",
        )
    finally:
        db.close()


# ---------------------------------------------------------
# ANALYTICS CSV UPLOAD
# ---------------------------------------------------------

def normalize_column_name(name: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        name.strip().lower(),
    ).strip("_")


def find_column(
    normalized_row: dict,
    candidates: list[str],
) -> Optional[str]:
    for candidate in candidates:
        if candidate in normalized_row:
            return candidate
    return None


def safe_number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "").replace("$", "")
    text = text.replace("₹", "")
    if not text:
        return 0.0
    try:
        number = float(text)
        return number if number >= 0 else 0.0
    except (ValueError, TypeError):
        return 0.0


@app.post("/analytics/upload")
async def upload_analytics_csv(
    file: UploadFile = File(...),
    campaign_id: Optional[int] = Form(None),
):
    filename = file.filename or "analytics.csv"

    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a CSV file.",
        )

    try:
        raw_content = await file.read()
        if not raw_content:
            raise HTTPException(
                status_code=400,
                detail="The uploaded CSV file is empty.",
            )

        try:
            content = raw_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw_content.decode("latin-1")

        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            raise HTTPException(
                status_code=400,
                detail="The CSV file must contain a header row.",
            )

        totals = {
            "impressions": 0.0,
            "clicks": 0.0,
            "engagements": 0.0,
            "conversions": 0.0,
            "spend": 0.0,
        }

        rows_processed = 0

        for row in reader:
            normalized_row = {
                normalize_column_name(key or ""): value
                for key, value in row.items()
                if key is not None
            }

            columns = {
                "impressions": [
                    "impressions", "impression", "views", "reach"
                ],
                "clicks": ["clicks", "click"],
                "engagements": [
                    "engagements", "engagement", "interactions"
                ],
                "conversions": [
                    "conversions", "conversion", "leads", "purchases"
                ],
                "spend": [
                    "spend", "cost", "amount_spent", "ad_spend"
                ],
            }

            for metric, candidates in columns.items():
                column = find_column(normalized_row, candidates)
                if column is not None:
                    totals[metric] += safe_number(normalized_row[column])

            rows_processed += 1

        if rows_processed == 0:
            raise HTTPException(
                status_code=400,
                detail="The CSV contains no data rows.",
            )

        impressions = totals["impressions"]
        clicks = totals["clicks"]
        engagements = totals["engagements"]
        conversions = totals["conversions"]
        spend = totals["spend"]

        ctr = (clicks / impressions * 100) if impressions else 0.0
        engagement_rate = (
            engagements / impressions * 100
            if impressions else 0.0
        )
        conversion_rate = (
            conversions / clicks * 100
            if clicks else 0.0
        )
        cost_per_conversion = (
            spend / conversions
            if conversions else 0.0
        )

        calculated_results = {
            "rows_processed": rows_processed,
            "totals": {
                key: round(value, 2)
                for key, value in totals.items()
            },
            "metrics": {
                "ctr": round(ctr, 2),
                "engagement_rate": round(engagement_rate, 2),
                "conversion_rate": round(conversion_rate, 2),
                "cost_per_conversion": round(cost_per_conversion, 2),
            },
            "metric_definitions": {
                "ctr": "Clicks / impressions * 100",
                "engagement_rate": "Engagements / impressions * 100",
                "conversion_rate": "Conversions / clicks * 100",
                "cost_per_conversion": "Spend / conversions",
            },
            "data_type": "Uploaded CSV data; verify whether it is actual or sample data.",
        }

        # Optionally attach the latest uploaded analytics to a campaign record.
        if campaign_id is not None:
            db = SessionLocal()
            try:
                campaign = (
                    db.query(Campaign)
                    .filter(Campaign.id == campaign_id)
                    .first()
                )
                if not campaign:
                    raise HTTPException(
                        status_code=404,
                        detail="Campaign not found.",
                    )

                results = parse_json(campaign.results, {})
                results["uploaded_analytics"] = calculated_results
                campaign.results = json.dumps(
                    results,
                    ensure_ascii=False,
                )
                db.commit()
            except HTTPException:
                db.rollback()
                raise
            except Exception:
                db.rollback()
                logger.exception("Could not attach analytics to campaign.")
                raise HTTPException(
                    status_code=500,
                    detail="Analytics were processed but could not be saved.",
                )
            finally:
                db.close()

        return {
            "message": "CSV processed successfully",
            "filename": filename,
            "rows_processed": rows_processed,
            "totals": calculated_results["totals"],
            "metrics": calculated_results["metrics"],
            "calculated_results": calculated_results,
            "note": (
                "Verify whether the uploaded values are actual campaign "
                "data or sample data before reporting them as actual results."
            ),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analytics CSV processing failed.")
        raise HTTPException(
            status_code=500,
            detail=f"Could not process analytics CSV: {str(exc)}",
        )
    finally:
        await file.close()


# ---------------------------------------------------------
# STARTUP MESSAGE
# ---------------------------------------------------------

@app.on_event("startup")
def startup_message():
    logger.info("%s is ready.", APP_NAME)
    logger.info("API documentation: /docs")
    logger.info("Gemini enabled: %s", bool(gemini_client))
