# ⚡ Rezum AI - Telegram ATS Resume Evaluator

**Rezum AI** is a Telegram bot designed to evaluate candidate resumes against Job Descriptions (JDs) using LLM reasoning (via Groq API). It extracts key qualifications, identifies missing critical skills, provides candidate recommendations, and generates customized learning paths with course links.

---

## ✨ Features

- 📑 **Flexible Inputs**: Supports text pasting, PDF files, and Word (`.docx`) documents for both JDs and resumes.
- 📦 **Batch Processing**: Handles multi-file uploads and compressed `.ZIP` archives (evaluating up to 10+ resumes in a single session).
- 🎯 **ATS Score Card**: Produces candidate match percentages, detailed executive summaries, matched core skills, and critical gaps.
- 📊 **Detailed Category Breakdown**: Interactive Telegram inline buttons expand visual score meters across 7 technical & professional categories.
- 📚 **Personalized Course Recommendations**: Generates search links for Coursera and other learning platforms tailored to candidate skill gaps.

---

## 🛠️ Tech Stack

- **Language**: Python 3.9+
- **Bot Framework**: `python-telegram-bot`
- **LLM Engine**: Groq API (`openai` SDK interface with models like LLaMA 3.3 70B)
- **Document Parsers**: `pypdf`, `python-docx`
- **Environment Management**: `python-dotenv`

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.9 or higher installed.
- A Telegram Bot Token obtained from [@BotFather](https://t.me/BotFather).
- A Groq API key obtained from the [Groq Console](https://console.groq.com/).

### 2. Installation

1. **Clone the repository**:
   ```bash
   git clone [https://github.com/YOUR_USERNAME/Rezum-AI.git](https://github.com/YOUR_USERNAME/Rezum-AI.git)
   cd Rezum-AI
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   Create a `Tokens.env` file in the project root directory:
   ```env
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   GROQ_API_KEY=your_groq_api_key_here
   ```

---

## 🤖 Usage

1. Start the bot:
   ```bash
   python bot.py
   ```
2. Open your bot on Telegram and run `/start`.
3. **Step 1**: Send or upload your Job Description (or send `/skip` for general evaluation).
4. **Step 2**: Upload one or more resumes (`.pdf`, `.docx`, or a `.zip` archive).
5. Tap **`/analyze`** to generate the candidate evaluations.

---

## 🛡️ License

Distributed under the MIT License. See `LICENSE` for details.