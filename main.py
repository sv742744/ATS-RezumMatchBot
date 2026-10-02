import io
import json
import logging
import os
import urllib.parse
import zipfile
from dotenv import load_dotenv
from docx import Document as DocxDocument
from pypdf import PdfReader
from openai import OpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv("Tokens.env.example")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_BOT_TOKEN or not GROQ_API_KEY:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or GROQ_API_KEY in Tokens.env file.")

# Initialize logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Initialize OpenAI Client configured specifically for Groq API backend
groq_client = OpenAI(
    api_key=GROQ_API_KEY.strip(),
    base_url="https://api.groq.com/openai/v1",
)

# Define Conversation States
AWAITING_JD, AWAITING_RESUMES = range(2)


def get_available_groq_model() -> str:
    """Dynamically fetches available models from Groq, filtering out restricted ones."""
    try:
        models = groq_client.models.list()
        model_ids = [m.id for m in models.data]

        preferred_keywords = [
            "llama-3.3-70b",
            "llama-3.2",
            "llama-3.1",
            "llama3-70b",
            "llama3-8b",
            "mixtral",
        ]

        excluded_keywords = ["whisper", "allam", "guard", "vision", "canopylabs", "orpheus", "compound"]

        for pref in preferred_keywords:
            for m_id in model_ids:
                if pref in m_id.lower() and not any(ex in m_id.lower() for ex in excluded_keywords):
                    return m_id

        for m_id in model_ids:
            if not any(ex in m_id.lower() for ex in excluded_keywords):
                return m_id

        return model_ids[0] if model_ids else "llama-3.3-70b-versatile"
    except Exception as e:
        logging.warning(f"Could not check Groq models list: {e}")
        return "llama-3.3-70b-versatile"


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extracts clean text from raw PDF bytes."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text.strip()
    except Exception as e:
        logging.error(f"Failed to extract PDF text: {e}")
        return ""


def extract_text_from_docx(docx_bytes: bytes) -> str:
    """Extracts clean text from DOCX document bytes."""
    try:
        doc = DocxDocument(io.BytesIO(docx_bytes))
        text = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
        return "\n".join(text).strip()
    except Exception as e:
        logging.error(f"Failed to extract DOCX text: {e}")
        return ""


def make_progress_bar(score: int) -> str:
    """Generates a visual progress bar e.g. ████████░░."""
    score = max(0, min(100, score))
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the bot conversation and requests Job Description."""
    context.user_data.clear()
    context.user_data["resumes"] = []

    welcome_text = (
        "👋 **Welcome to Rezum - AI Resume Matcher!**\n\n"
        "1️⃣ **Step 1:** Paste/type the **Job Description (JD)** or upload a **PDF/DOCX JD** below.\n"
        "*(Or send /skip if you want a general resume assessment)*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    return AWAITING_JD


async def receive_jd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores Job Description (from text, PDF, or DOCX) and asks for Resume uploads."""
    jd_text = ""

    if update.message.document:
        document = update.message.document
        filename = document.file_name.lower()

        try:
            file_obj = await document.get_file()
            file_bytes = await file_obj.download_as_bytearray()
            
            if filename.endswith(".pdf"):
                jd_text = extract_text_from_pdf(bytes(file_bytes))
            elif filename.endswith(".docx") or filename.endswith(".doc"):
                jd_text = extract_text_from_docx(bytes(file_bytes))
            else:
                await update.message.reply_text("⚠️ Please send a `.pdf` or `.docx` document, or paste the text directly.")
                return AWAITING_JD

            if not jd_text:
                await update.message.reply_text("❌ Could not extract text from the JD file. Please paste the text directly.")
                return AWAITING_JD

        except (TimedOut, NetworkError):
            await update.message.reply_text("⏳ Telegram connection timed out while reading the file. Please re-upload your JD.")
            return AWAITING_JD
    elif update.message.text:
        jd_text = update.message.text.strip()

    if not jd_text:
        await update.message.reply_text("⚠️ Please provide a valid Job Description.")
        return AWAITING_JD

    context.user_data["jd"] = jd_text

    next_step_text = (
        "✅ **Job Description Received!**\n\n"
        "2️⃣ **Step 2: Upload candidate Resumes.**\n"
        "• Upload individual PDF or Word (.docx) files\n"
        "• Or upload a single .ZIP file containing multiple resume documents\n\n"
        "When finished uploading, tap 👉 /analyze"
    )
    await update.message.reply_text(next_step_text, parse_mode="Markdown")
    return AWAITING_RESUMES


async def skip_jd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skips JD input for general review."""
    context.user_data["jd"] = "General Software Engineering and Technical Professional Standards"

    next_step_text = (
        "⏩ **Skipped JD.** Resumes will be evaluated against general industry standards.\n\n"
        "2️⃣ **Step 2: Upload candidate Resumes.**\n"
        "• Upload individual PDF or Word (.docx) files\n"
        "• Or upload a single .ZIP file containing multiple resume documents\n\n"
        "When finished uploading, tap 👉 /analyze"
    )
    await update.message.reply_text(next_step_text, parse_mode="Markdown")
    return AWAITING_RESUMES


async def receive_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles PDF, DOCX, and ZIP document uploads for candidate resumes."""
    document = update.message.document
    filename = document.file_name.lower()

    try:
        file_obj = await document.get_file()
        file_bytes = await file_obj.download_as_bytearray()
    except (TimedOut, NetworkError):
        await update.message.reply_text("⏳ Network timeout while downloading document. Please re-upload the file.")
        return AWAITING_RESUMES

    if filename.endswith(".pdf"):
        extracted_text = extract_text_from_pdf(bytes(file_bytes))
        if extracted_text:
            context.user_data["resumes"].append({"name": document.file_name, "text": extracted_text})
            await update.message.reply_text(
                f"✅ **Saved:** `{document.file_name}`\n"
                f"📊 **Total Resumes Ready:** {len(context.user_data['resumes'])}\n\n"
                "Upload more or tap 👉 /analyze",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("❌ Could not read text from this PDF.")

    elif filename.endswith(".docx") or filename.endswith(".doc"):
        extracted_text = extract_text_from_docx(bytes(file_bytes))
        if extracted_text:
            context.user_data["resumes"].append({"name": document.file_name, "text": extracted_text})
            await update.message.reply_text(
                f"✅ **Saved:** `{document.file_name}`\n"
                f"📊 **Total Resumes Ready:** {len(context.user_data['resumes'])}\n\n"
                "Upload more or tap 👉 /analyze",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("❌ Could not read text from this Word document.")

    elif filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                added_count = 0
                for fname in z.namelist():
                    lower_f = fname.lower()
                    if not fname.startswith("__MACOSX"):
                        file_data = z.read(fname)
                        extracted_text = ""
                        
                        if lower_f.endswith(".pdf"):
                            extracted_text = extract_text_from_pdf(file_data)
                        elif lower_f.endswith(".docx") or lower_f.endswith(".doc"):
                            extracted_text = extract_text_from_docx(file_data)

                        if extracted_text:
                            context.user_data["resumes"].append({"name": os.path.basename(fname), "text": extracted_text})
                            added_count += 1

                await update.message.reply_text(
                    f"📦 **Extracted {added_count} candidate file(s) from ZIP archive!**\n"
                    f"📊 **Total Resumes Ready:** {len(context.user_data['resumes'])}\n\n"
                    "Upload more or tap 👉 /analyze",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logging.error(f"Error handling ZIP: {e}")
            await update.message.reply_text("❌ Failed to process the ZIP archive.")
    else:
        await update.message.reply_text("⚠️ Please send `.pdf` or `.docx` files, or a `.zip` archive containing documents.")

    return AWAITING_RESUMES


async def handle_score_breakdown_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback handler to display full 7-category score breakdown when requested by user."""
    query = update.callback_query
    await query.answer()

    data_key = query.data
    s = context.user_data.get("breakdowns", {}).get(data_key, {})

    if not s:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    tech = s.get("primary_technical_stack", {}).get("score", 0)
    tech_note = s.get("primary_technical_stack", {}).get("note", "N/A")

    devops = s.get("infrastructure_devops", {}).get("score", 0)
    devops_note = s.get("infrastructure_devops", {}).get("note", "N/A")

    arch = s.get("systems_architecture", {}).get("score", 0)
    arch_note = s.get("systems_architecture", {}).get("note", "N/A")

    testing = s.get("testing_qa", {}).get("score", 0)
    testing_note = s.get("testing_qa", {}).get("note", "N/A")

    tenure = s.get("industry_tenure_depth", {}).get("score", 0)
    tenure_note = s.get("industry_tenure_depth", {}).get("note", "N/A")

    stakeholder = s.get("client_stakeholder_work", {}).get("score", 0)
    stakeholder_note = s.get("client_stakeholder_work", {}).get("note", "N/A")

    academic = s.get("academic_certification", {}).get("score", 0)
    academic_note = s.get("academic_certification", {}).get("note", "N/A")

    breakdown_text = (
        f"{query.message.text}\n\n"
        f"------------------------------------------------\n"
        f"📊 **COMPREHENSIVE CATEGORY SCORE BREAKDOWN**\n"
        f"------------------------------------------------\n"
        f"• **Primary Technical Stack**  : [{make_progress_bar(tech)}] {tech}/100 ({tech_note})\n"
        f"• **Infrastructure & DevOps**  : [{make_progress_bar(devops)}] {devops}/100 ({devops_note})\n"
        f"• **Systems Architecture**    : [{make_progress_bar(arch)}] {arch}/100 ({arch_note})\n"
        f"• **Testing & Quality Assur.** : [{make_progress_bar(testing)}] {testing}/100 ({testing_note})\n"
        f"• **Industry Tenure Depth**   : [{make_progress_bar(tenure)}] {tenure}/100 ({tenure_note})\n"
        f"• **Client & Stakeholder Work**: [{make_progress_bar(stakeholder)}] {stakeholder}/100 ({stakeholder_note})\n"
        f"• **Academic & Certification** : [{make_progress_bar(academic)}] {academic}/100 ({academic_note})"
    )

    await query.edit_message_text(text=breakdown_text, parse_mode="Markdown", disable_web_page_preview=True)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Invokes API backend to evaluate resumes against multi-category ATS scoring standards."""
    resumes = context.user_data.get("resumes", [])
    jd = context.user_data.get("jd", "")

    if not resumes:
        await update.message.reply_text(
            "⚠️ Upload at least one PDF/DOCX resume or ZIP archive before running /analyze."
        )
        return AWAITING_RESUMES

    await update.message.reply_text(
        f"⚡ **Evaluating {len(resumes)} resume(s) with Rezum AI...**\nPlease wait a few seconds.",
        parse_mode="Markdown"
    )

    prompt = f"""
    You are an expert ATS (Applicant Tracking System) Evaluator and Senior Technical Recruiter.
    Analyze the candidate's resume against the Job Description.

    JOB DESCRIPTION:
    {jd}

    RESUMES:
    """
    for idx, r in enumerate(resumes, 1):
        prompt += f"\n--- RESUME #{idx} (Filename: {r['name']}) ---\n{r['text']}\n"

    prompt += """
    Output a single JSON object containing an "evaluations" array.
    
    Strict Rules:
    - Determine Match Level: High Match (80-100%) | Moderate Match (50-79%) | Low Match (0-49%)
    - Provide EXACTLY 2 recommended courses per candidate (no more, no less).

    JSON Structure:
    {
      "evaluations": [
        {
          "filename": "file.pdf",
          "candidate_name": "Candidate Full Name",
          "role_evaluated": "Job Title from JD",
          "match_level": "High Match (80-100%)",
          "overall_score": 85,
          "category_breakdown": {
             "primary_technical_stack": {"score": 90, "note": "Key Frameworks/Tools"},
             "infrastructure_devops": {"score": 60, "note": "Cloud, CI/CD, Containers"},
             "systems_architecture": {"score": 70, "note": "Microservices/Design"},
             "testing_qa": {"score": 40, "note": "Automated Testing, Standards"},
             "industry_tenure_depth": {"score": 60, "note": "Years vs. Required Level"},
             "client_stakeholder_work": {"score": 90, "note": "Agile, Client-Facing"},
             "academic_certification": {"score": 70, "note": "Degrees, Certifications"}
          },
          "executive_summary": "2-3 sentence overview justifying rating based on strengths and critical gaps.",
          "matched_core_skills": [
             {"skill": "Skill Name 1", "context": "Brief context from resume"}
          ],
          "critical_missing_requirements": [
             {"requirement": "Requirement Name 1", "reason": "Reason candidate falls short"}
          ],
          "minor_preferred_gaps": [
             {"requirement": "Requirement Name 1", "note": "Brief note"}
          ],
          "actionable_recommendations": [
             "Actionable step 1",
             "Actionable step 2",
             "Actionable step 3",
             "Actionable step 4"
          ],
          "recommended_courses": [
             {
               "title": "Course Title 1",
               "platform": "Coursera / Udemy / edX / Pluralsight",
               "target_gap": "Specific missing skill addressed"
             },
             {
               "title": "Course Title 2",
               "platform": "Coursera / Udemy / edX / Pluralsight",
               "target_gap": "Specific missing skill addressed"
             }
          ]
        }
      ]
    }
    """

    try:
        model_to_use = get_available_groq_model()
        logging.info(f"Using model: {model_to_use}")

        response = groq_client.chat.completions.create(
            model=model_to_use,
            messages=[
                {
                    "role": "system",
                    "content": "You are Rezum AI, a senior recruiter. Output strict, valid JSON matching the exact schema requested.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        response_text = response.choices[0].message.content.strip()
        parsed_obj = json.loads(response_text)
        
        data = parsed_obj.get("evaluations", []) if isinstance(parsed_obj, dict) else parsed_obj

        if "breakdowns" not in context.user_data:
            context.user_data["breakdowns"] = {}

        for index, item in enumerate(data):
            cand_name = item.get("candidate_name", "N/A")
            role = item.get("role_evaluated", "N/A")
            match_lvl = item.get("match_level", "Moderate Match (50-79%)")
            score = item.get("overall_score", 0)
            summary = item.get("executive_summary", "")

            # Core skills (handles string or dict defensively)
            matched = item.get("matched_core_skills", [])
            matched_lines = []
            for m in matched:
                if isinstance(m, dict):
                    matched_lines.append(f"• **{m.get('skill', 'Skill')}**: {m.get('context', 'Demonstrated in experience')}")
                else:
                    matched_lines.append(f"• **{m}**")
            matched_str = "\n".join(matched_lines) if matched_lines else "• None identified"

            # Critical gaps (handles string or dict defensively)
            critical = item.get("critical_missing_requirements", [])
            critical_lines = []
            for c in critical:
                if isinstance(c, dict):
                    critical_lines.append(f"• **{c.get('requirement', 'Requirement')}**: {c.get('reason', 'Missing from experience')}")
                else:
                    critical_lines.append(f"• **{c}**")
            critical_str = "\n".join(critical_lines) if critical_lines else "• None identified"

            # Minor gaps (handles string or dict defensively)
            minor = item.get("minor_preferred_gaps", [])
            minor_lines = []
            for m in minor:
                if isinstance(m, dict):
                    minor_lines.append(f"• **{m.get('requirement', 'Requirement')}**: {m.get('note', 'Minor area for improvement')}")
                else:
                    minor_lines.append(f"• **{m}**")
            minor_str = "\n".join(minor_lines) if minor_lines else "• None identified"

            # Action steps
            recs = item.get("actionable_recommendations", [])
            recs_str = "\n".join([f"{idx+1}. {r}" for idx, r in enumerate(recs)]) if recs else "1. Continue maintaining skills aligned with current industry standards."

            # Courses (strictly 2 max, handles string or dict defensively)
            courses = item.get("recommended_courses", [])[:2]
            courses_list = []
            for c in courses:
                if isinstance(c, dict):
                    ctitle = c.get("title", "Course")
                    cplat = c.get("platform", "Coursera")
                    cgap = c.get("target_gap", "Skill Gap")
                else:
                    ctitle = str(c)
                    cplat = "Coursera"
                    cgap = "Skill Gap"
                
                encoded = urllib.parse.quote(f"{ctitle} {cplat}")
                curl = f"https://www.coursera.org/search?query={encoded}"
                courses_list.append(f"• **[{ctitle}]({curl})**\n  - Platform: {cplat}\n  - Target Gap: {cgap}")

            courses_str = "\n".join(courses_list) if courses_list else "No additional courses required."

            card = (
                f"================================================\n"
                f"            **REZUM ATS CANDIDATE EVALUATION**\n"
                f"================================================\n\n"
                f"👤 **CANDIDATE:** {cand_name}\n"
                f"💼 **ROLE EVALUATED:** {role}\n"
                f"🎯 **MATCH LEVEL:** `{match_lvl}`\n"
                f"📊 **OVERALL SCORE:** {score}/100\n\n"
                f"------------------------------------------------\n"
                f"🎯 **EXECUTIVE SUMMARY**\n"
                f"------------------------------------------------\n"
                f"{summary}\n\n"
                f"------------------------------------------------\n"
                f"🧩 **SKILL ALIGNMENT BREAKDOWN**\n"
                f"------------------------------------------------\n"
                f"✅ **MATCHED CORE SKILLS**\n{matched_str}\n\n"
                f"⚠️ **CRITICAL MISSING REQUIREMENTS**\n{critical_str}\n\n"
                f"ℹ️ **MINOR/PREFERRED GAPS**\n{minor_str}\n\n"
                f"------------------------------------------------\n"
                f"💡 **ACTIONABLE RECOMMENDATIONS FOR CANDIDATE**\n"
                f"------------------------------------------------\n{recs_str}\n\n"
                f"------------------------------------------------\n"
                f"📚 **RECOMMENDED COURSES TO BRIDGE GAPS**\n"
                f"------------------------------------------------\n{courses_str}\n"
                f"================================================"
            )

            # Store score breakdown for optional inline button view
            breakdown_key = f"breakdown_{index}"
            context.user_data["breakdowns"][breakdown_key] = item.get("category_breakdown", {})

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Detailed Score Breakdown", callback_data=breakdown_key)]
            ])

            await update.message.reply_text(
                card, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=keyboard
            )

    except Exception as e:
        logging.error(f"Execution Error: {e}")
        await update.message.reply_text(f"❌ API Error: {str(e)}")

    await update.message.reply_text(
        "✨ **Evaluation complete!** Tap /start to evaluate another candidate or JD.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels evaluation flow."""
    context.user_data.clear()
    await update.message.reply_text("🚫 Evaluation canceled. Tap /start whenever you want to begin again.")
    return ConversationHandler.END


def main():
    """Starts the Telegram Bot."""
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .read_timeout(60.0)
        .connect_timeout(60.0)
        .write_timeout(60.0)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AWAITING_JD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_jd),
                MessageHandler(filters.Document.ALL, receive_jd),
                CommandHandler("skip", skip_jd),
            ],
            AWAITING_RESUMES: [
                MessageHandler(filters.Document.ALL, receive_document),
                CommandHandler("analyze", analyze),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_score_breakdown_button))

    print("Rezum Bot is active and running...")
    application.run_polling()


if __name__ == "__main__":
    main()