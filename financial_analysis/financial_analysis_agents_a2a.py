"""
LangChain Multi-Agent Financial Analysis System - HEXR A2A Enhanced
===================================================================

A comprehensive financial analysis system with specialized agents.

Agents:
- Research Agent: Gathers market data and financial information
- Analysis Agent: Performs quantitative analysis and modeling
- Risk Agent: Evaluates risks and compliance requirements
- Report Agent: Synthesizes findings into actionable reports
- Orchestrator: Coordinates the entire workflow

Pattern: Function-based tools with HEXR enterprise integration

Hexr Concepts Demonstrated:
  - @hexr_agent    → Register agent classes, discovered by `hexr build` (docs.hexr.dev/sdk/hexr-agent)
  - hexr_tool()    → Cloud credentials via SPIFFE identity (docs.hexr.dev/sdk/hexr-tool)
  - hexr_llm()     → LLM client wrapper with OTel + LLM Guard (docs.hexr.dev/sdk/hexr-llm)
  - A2ABridge      → Expose agent over A2A protocol (docs.hexr.dev/sdk/hexr-a2a)
  - VaultClient    → Fetch secrets via SPIFFE identity (docs.hexr.dev/sdk/vault)

A2A Flow:
    External caller -> Envoy -> A2A Sidecar :8090 -> Bridge :8080 /execute
    -> handle_analysis_request() -> 5-agent pipeline -> artifacts -> back
"""

import asyncio
import hexr
from hexr import hexr_llm
import logging
import time
import os
import openai
from hexr.a2a.bridge import A2ABridge
from hexr.a2a.models import Message, Artifact, TextPart
from hexr.vault import VaultClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_openai_key() -> str | None:
    """Fetch OpenAI API key from Hexr Vault, fallback to env var for local dev."""
    # Production path: fetch from Hexr Vault (SPIFFE-authenticated)
    try:
        vault = VaultClient()
        key = vault.get("api-keys/openai")
        logger.info("✅ OpenAI API key fetched from Hexr Vault")
        return key
    except Exception as e:
        logger.debug(f"Vault unavailable ({e}), trying env var fallback")
    # Fallback for local development
    return os.environ.get("OPENAI_API_KEY")


# ── hexr_llm: wrap the OpenAI client for automatic OTel instrumentation ──
# Every call through this client gets a span with model, tokens, latency.
_api_key = _get_openai_key()
_llm_client = hexr_llm(openai.OpenAI(api_key=_api_key)) if _api_key else None


# ============================================================================
# TOOL DEFINITIONS - Simple Python functions
# ============================================================================

def collect_market_data(query: str) -> str:
    """
    Collect market data and financial metrics for a company or market.
    
    Args:
        query: Company name, ticker symbol, or market segment to research
        
    Returns:
        Market data summary including prices, trends, and volume analysis
    """
    # Test S3 credential exchange via SPIFFE→AWS federation
    s3 = hexr.hexr_tool('aws_s3')
    buckets = s3.list_buckets()
    print(f"✅ S3 Access: Listed {len(buckets['Buckets'])} buckets")
    
    return f"Market data collected for {query}: Price trends showing 15% YoY growth, volume up 22%, sector performance strong"


def research_company(company: str) -> str:
    """
    Research company fundamentals, news, and competitive position.
    Uses hexr_llm() for LLM-powered research with OTel GenAI span capture.
    
    Args:
        company: Company name or ticker symbol
        
    Returns:
        Company research summary including fundamentals and recent news
    """
    # Test S3 credential exchange via SPIFFE→AWS federation
    s3 = hexr.hexr_tool('aws_s3')
    buckets = s3.list_buckets()
    print(f"✅ S3 Access: Listed {len(buckets['Buckets'])} buckets")

    if _llm_client is not None:
        try:
            resp = _llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an equity research analyst. Provide a concise 3-bullet company overview covering fundamentals, recent news, and competitive position."},
                    {"role": "user", "content": f"Research company: {company}"},
                ],
                max_tokens=250,
                temperature=0.3,
            )
            result = resp.choices[0].message.content
            tokens_in = getattr(resp.usage, "prompt_tokens", "?")
            tokens_out = getattr(resp.usage, "completion_tokens", "?")
            logger.info(f"✅ hexr_llm research_company: {tokens_in} in / {tokens_out} out tokens")
            return f"Company Research (LLM):\n{result}"
        except Exception as e:
            logger.warning(f"hexr_llm call failed, falling back to static: {e}")

    return f"Company research completed for {company}: Strong fundamentals, positive news sentiment, growing market share"


def build_financial_model(parameters: str) -> str:
    """
    Build and execute financial models for valuation and forecasting.
    
    Args:
        parameters: Model parameters including revenue projections, growth rates, discount rates
        
    Returns:
        Financial model results with key metrics
    """
    # Test S3 credential exchange via SPIFFE→AWS federation
    s3 = hexr.hexr_tool('aws_s3')
    buckets = s3.list_buckets()
    print(f"✅ S3 Access: Listed {len(buckets['Buckets'])} buckets")
    
    return f"Financial model built: DCF valuation $125M, IRR 18%, NPV $45M, payback period 4.2 years"


def calculate_risk_metrics(data: str) -> str:
    """
    Calculate comprehensive risk metrics for investment analysis.
    
    Args:
        data: Investment or portfolio data for risk assessment
        
    Returns:
        Risk metrics including VaR, volatility, and scenario analysis
    """
    # Test S3 credential exchange via SPIFFE→AWS federation
    s3 = hexr.hexr_tool('aws_s3')
    buckets = s3.list_buckets()
    print(f"✅ S3 Access: Listed {len(buckets['Buckets'])} buckets")
    
    return f"Risk metrics calculated: VaR (95%) $2.3M, Sharpe ratio 1.45, max drawdown 12%, beta 0.85"


def perform_valuation(company_data: str) -> str:
    """
    Perform comprehensive company valuation using multiple methodologies.
    
    Args:
        company_data: Company financial data and metrics
        
    Returns:
        Valuation results using DCF, comparable companies, and precedent transactions
    """
    # REMOVED FAKE SERVICE: dcf_value = hexr.hexr_tool('dcf_valuation_engine')(financials=company_data)
    # REMOVED FAKE SERVICE: multiples = hexr.hexr_tool('market_multiples_analyzer')(company=company_data, peers=True)
    
    return f"Valuation completed: DCF $125M, Comparable companies $118M-$135M, Target price $130M"


def check_compliance(requirements: str) -> str:
    """
    Check regulatory compliance requirements for investment or transaction.
    
    Args:
        requirements: Compliance requirements or regulatory framework to check
        
    Returns:
        Compliance assessment with gap analysis
    """
    # REMOVED FAKE SERVICE: scan_results = hexr.hexr_tool('regulatory_compliance_scanner')(requirements=requirements, jurisdiction='US')
    # REMOVED FAKE SERVICE: gap_analysis = hexr.hexr_tool('compliance_gap_analyzer')(findings=scan_results)
    
    return f"Compliance check completed: All SOX requirements met, SEC filings current, no material gaps identified"


def assess_risks(scenario: str) -> str:
    """
    Assess various risk scenarios including market, credit, operational risks.
    Uses hexr_llm() for LLM-powered risk analysis with OTel GenAI span capture.
    
    Args:
        scenario: Risk scenario to assess
        
    Returns:
        Risk assessment with mitigation recommendations
    """
    if _llm_client is not None:
        try:
            resp = _llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a risk analyst. Assess market, credit, and operational risks in 3-4 concise sentences. Include risk level ratings."},
                    {"role": "user", "content": f"Risk assessment for scenario: {scenario}"},
                ],
                max_tokens=200,
                temperature=0.2,
            )
            result = resp.choices[0].message.content
            tokens_in = getattr(resp.usage, "prompt_tokens", "?")
            tokens_out = getattr(resp.usage, "completion_tokens", "?")
            logger.info(f"✅ hexr_llm assess_risks: {tokens_in} in / {tokens_out} out tokens")
            return f"Risk Assessment (LLM):\n{result}"
        except Exception as e:
            logger.warning(f"hexr_llm call failed, falling back to static: {e}")

    return f"Risk assessment completed: Market risk moderate, credit risk low, operational risks identified with mitigations"


def generate_report(analysis_data: str) -> str:
    """
    Generate comprehensive financial reports from analysis data.
    
    Args:
        analysis_data: Analysis results to include in report
        
    Returns:
        Formatted financial report
    """
    # REMOVED FAKE SERVICE: report = hexr.hexr_tool('financial_report_generator')(data=analysis_data, format='PDF')
    # REMOVED FAKE SERVICE: validation = hexr.hexr_tool('report_quality_validator')(report=report)
    
    return f"Financial report generated: 45-page analysis with executive summary, detailed findings, and recommendations"


def create_executive_summary(full_analysis: str) -> str:
    """
    Create executive summary from full analysis.
    Uses hexr_llm()-wrapped OpenAI client for LLM-powered summarisation
    with automatic OTel span capture (model, tokens, latency).
    Falls back to static text when no API key is available.

    Args:
        full_analysis: Full analysis results to summarize

    Returns:
        Executive summary with key insights
    """
    if _llm_client is not None:
        try:
            resp = _llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a senior investment analyst. Write a concise 3-sentence executive summary."},
                    {"role": "user", "content": f"Summarise this analysis:\n{full_analysis}"},
                ],
                max_tokens=200,
                temperature=0.3,
            )
            summary = resp.choices[0].message.content
            tokens_in = getattr(resp.usage, "prompt_tokens", "?")
            tokens_out = getattr(resp.usage, "completion_tokens", "?")
            logger.info(f"✅ hexr_llm exec-summary: {tokens_in} in / {tokens_out} out tokens")
            return f"Executive Summary (LLM):\n{summary}"
        except Exception as e:
            logger.warning(f"hexr_llm call failed, falling back to static: {e}")

    return f"Executive summary created: Strong buy recommendation, target valuation $130M, 12-month price target $155/share"


def coordinate_analysis_workflow(workflow_params: str) -> str:
    """
    Coordinate multi-agent analysis workflow with proper sequencing.
    
    Args:
        workflow_params: Parameters for workflow coordination
        
    Returns:
        Workflow coordination status
    """
    # REMOVED FAKE SERVICE: orchestration = hexr.hexr_tool('investment_opportunity_orchestrator')(params=workflow_params)
    # REMOVED FAKE SERVICE: coordination = hexr.hexr_tool('multi_agent_workflow_coordinator')(workflow=workflow_params, agents=['research', 'analysis', 'risk', 'reporting'])
    
    return f"Workflow coordinated: All phases completed successfully, analysis ready for review"


def synthesize_results(all_results: str) -> str:
    """
    Synthesize results from all analysis agents into final recommendation.
    Uses hexr_llm() for LLM-powered synthesis with OTel GenAI span capture.
    
    Args:
        all_results: Combined results from research, analysis, risk agents
        
    Returns:
        Final synthesized recommendation
    """
    if _llm_client is not None:
        try:
            resp = _llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a senior investment strategist. Synthesize the analysis into a final investment recommendation in 3-4 sentences. Include a clear BUY/HOLD/SELL rating with target valuation."},
                    {"role": "user", "content": f"Synthesize these multi-agent analysis results:\n{all_results}"},
                ],
                max_tokens=250,
                temperature=0.3,
            )
            result = resp.choices[0].message.content
            tokens_in = getattr(resp.usage, "prompt_tokens", "?")
            tokens_out = getattr(resp.usage, "completion_tokens", "?")
            logger.info(f"✅ hexr_llm synthesize: {tokens_in} in / {tokens_out} out tokens")
            return f"Synthesis (LLM):\n{result}"
        except Exception as e:
            logger.warning(f"hexr_llm call failed, falling back to static: {e}")

    return f"Final recommendation: STRONG BUY - Target valuation $130M, upside potential 35%, risk-adjusted return 18%"


# ============================================================================
# AGENT DEFINITIONS - Factory functions with @hexr.hexr_agent decorators
# ============================================================================

@hexr.hexr_agent(
    name="financial_research_analyst",
    role="Financial Research Analyst",
    capabilities=["market_data_collection", "company_research", "financial_metrics"],
    security_level="standard",
    resource_requirements={"cpu": "500m", "memory": "1Gi"},
    tenant="demo"
)
def create_financial_research_analyst():
    """
    Create financial research analyst agent.
    
    Capabilities:
    - Market data collection
    - Company fundamental research
    - Financial metrics gathering
    - News and sentiment analysis
    """
    print("  [Agent] Financial Research Analyst initialized")
    return {
        "name": "financial_research_analyst",
        "role": "Market Research Analyst",
        "tools": [collect_market_data, research_company],
        "status": "initialized"
    }


@hexr.hexr_agent(
    name="quantitative_analyst",
    role="Quantitative Financial Analyst",
    capabilities=["financial_modeling", "risk_calculation", "valuation_analysis"],
    security_level="standard",
    resource_requirements={"cpu": "800m", "memory": "2Gi"},
    tenant="demo"
)
def create_quantitative_analyst():
    """
    Create quantitative analysis agent.
    
    Capabilities:
    - Financial modeling and DCF analysis
    - Risk metric calculations
    - Valuation analysis
    - Monte Carlo simulations
    """
    print("  [Agent] Quantitative Analyst initialized")
    return {
        "name": "quantitative_analyst",
        "role": "Quantitative Financial Analyst",
        "tools": [build_financial_model, calculate_risk_metrics, perform_valuation],
        "status": "initialized"
    }


@hexr.hexr_agent(
    name="risk_compliance_analyst",
    role="Risk and Compliance Analyst",
    capabilities=["regulatory_compliance", "risk_assessment", "stress_testing"],
    security_level="elevated",
    resource_requirements={"cpu": "500m", "memory": "1Gi"},
    tenant="demo"
)
def create_risk_compliance_analyst():
    """
    Create risk and compliance analyst agent.
    
    Capabilities:
    - Regulatory compliance checking
    - Risk assessment
    - Stress testing
    - Gap analysis
    """
    print("  [Agent] Risk & Compliance Analyst initialized")
    return {
        "name": "risk_compliance_analyst",
        "role": "Risk and Compliance Analyst",
        "tools": [check_compliance, assess_risks],
        "status": "initialized"
    }


@hexr.hexr_agent(
    name="financial_report_generator",
    role="Financial Report Generator",
    capabilities=["report_generation", "executive_summaries", "data_visualization"],
    security_level="standard",
    resource_requirements={"cpu": "400m", "memory": "1Gi"},
    tenant="demo"
)
def create_financial_report_generator():
    """
    Create financial report generator agent.
    
    Capabilities:
    - Report generation
    - Executive summaries
    - Data visualization
    - Quality validation
    """
    print("  [Agent] Financial Report Generator initialized")
    return {
        "name": "financial_report_generator",
        "role": "Financial Report Generator",
        "tools": [generate_report, create_executive_summary],
        "status": "initialized"
    }


@hexr.hexr_agent(
    name="financial-analysis-orchestrator",
    role="Financial Analysis Orchestrator",
    capabilities=["workflow_coordination", "agent_management", "result_synthesis"],
    security_level="elevated",
    resource_requirements={"cpu": "600m", "memory": "1.5Gi"},
    tenant="demo",
    a2a=True,
    skills=[
        {
            "id": "financial-analysis",
            "name": "Financial Analysis",
            "description": "Run a comprehensive financial analysis pipeline: research, quantitative modeling, risk assessment, and executive report generation.",
        },
    ],
    description="LangChain-powered financial analysis system with 5 specialized agents. Send a company or sector name and receive a full investment analysis.",
)
def create_financial_analysis_orchestrator():
    """
    Create financial analysis orchestrator agent.
    
    Capabilities:
    - Workflow coordination
    - Agent management
    - Result synthesis
    - Quality assurance
    """
    print("  [Agent] Financial Analysis Orchestrator initialized")
    return {
        "name": "financial_analysis_orchestrator",
        "role": "Financial Analysis Orchestrator",
        "tools": [coordinate_analysis_workflow, synthesize_results],
        "status": "initialized"
    }


# ============================================================================
# A2A Handler — receives messages from the A2A sidecar, runs the pipeline
# ============================================================================

def handle_analysis_request(message: Message) -> str:
    """A2A handler: extract company/sector from message, run analysis pipeline.

    The Go A2A sidecar calls Bridge :8080 /execute which invokes this function.
    The message text is the company or sector to analyze.

    Returns:
        A text string that the bridge auto-wraps in an Artifact.
    """
    subject = message.text_content().strip() or "Tech sector"
    logger.info(f"A2A request received — subject: {subject}")

    # Initialize all 5 agents (decorators write marker files + set up context)
    research_agent = create_financial_research_analyst()
    quant_agent = create_quantitative_analyst()
    risk_agent = create_risk_compliance_analyst()
    report_agent = create_financial_report_generator()
    orchestrator_agent = create_financial_analysis_orchestrator()

    # Run the 5-step analysis pipeline using tool functions
    logger.info("[Step 1] Collecting market data...")
    market_data = collect_market_data(subject)

    logger.info("[Step 2] Researching company fundamentals...")
    company_research = research_company(subject)

    logger.info("[Step 3] Building financial model...")
    model_result = build_financial_model(f"revenue projections for {subject}")

    logger.info("[Step 4] Calculating risk metrics...")
    risk_metrics = calculate_risk_metrics(f"portfolio including {subject}")

    logger.info("[Step 5] Assessing risks (LLM)...")
    risk_assessment = assess_risks(f"investment in {subject}")

    logger.info("[Step 6] Synthesizing results (LLM)...")
    synthesis = synthesize_results(
        f"{market_data}\n{company_research}\n{model_result}\n{risk_metrics}\n{risk_assessment}"
    )

    logger.info("[Step 7] Generating executive summary (LLM)...")
    summary = create_executive_summary(
        f"{market_data}\n{company_research}\n{model_result}\n{risk_metrics}"
    )

    logger.info(f"A2A financial analysis complete for: {subject}")
    return (
        f"=== Financial Analysis Report ===\n"
        f"Subject: {subject}\n\n"
        f"Market Data:\n{market_data}\n\n"
        f"Company Research:\n{company_research}\n\n"
        f"Financial Model:\n{model_result}\n\n"
        f"Risk Metrics:\n{risk_metrics}\n\n"
        f"Risk Assessment:\n{risk_assessment}\n\n"
        f"Synthesis:\n{synthesis}\n\n"
        f"Executive Summary:\n{summary}"
    )


# ============================================================================
# MAIN EXECUTION — A2A Bridge (replaces keep-alive loop)
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("LangChain Financial Analysis System (A2A) - Starting")
    logger.info("=" * 80)

    # Start the A2A bridge — blocks forever, waiting for sidecar requests
    bridge = A2ABridge(handle_analysis_request)
    logger.info("A2A Bridge starting on 127.0.0.1:8080")
    asyncio.run(bridge.start())
