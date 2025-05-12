# WhatsApp Chat Analyzer

A web application that analyzes WhatsApp chat exports to extract coding tips, guidance, and resource links.

## Features

- Upload WhatsApp chat .txt files
- Extract coding tips and knowledge
- Identify and fetch titles for shared links
- Modern, responsive user interface
- Works locally on your computer (no data sent to external servers)

## Setup and Installation

1. Make sure you have Python 3.8+ installed on your computer.

2. Clone or download this repository.

3. Install the required dependencies:

```bash
pip install -r requirements.txt
```

4. Run the application:

```bash
python app.py
```

5. Open your web browser and go to: http://127.0.0.1:5000

## How to Use

1. Export your WhatsApp chat:
   - Open the WhatsApp chat you want to analyze
   - Tap the three dots menu (⋮) in the top right
   - Select "More" > "Export chat"
   - Choose "Without Media"
   - Save the .txt file

2. Upload the .txt file on the web application

3. View the extracted coding tips and resource links

## How It Works

The application uses natural language processing techniques to:
- Parse WhatsApp chat exports into structured data
- Identify messages related to coding and software development
- Extract potential tips, advice, and guidance
- Find URLs shared in the chat and fetch their page titles

## Technologies Used

- Flask: Web framework
- Beautiful Soup: Web scraping for link titles
- Sentence Transformers: Semantic analysis (when using local models)
- Python: Core programming language # whatsapp_chat_extractor
