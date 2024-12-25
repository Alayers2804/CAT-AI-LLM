import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from sqlalchemy import create_engine, Column, Integer, String, Date, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import openai
import logging

# Load environment variables
load_dotenv()

# Flask application setup
app = Flask(__name__)

logging.basicConfig(
    filename='app.log',  # Log file name
    level=logging.INFO,   # Log level
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log message format
)

# Database configuration
DB_NAME = os.getenv('DB_NAME')
DB_USERNAME = os.getenv('DB_USERNAME')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_URL = os.getenv('DB_URL')

# Create a connection to the MySQL server (without specifying a database)
engine = create_engine(f'mysql+mysqlconnector://{DB_USERNAME}:{DB_PASSWORD}@{DB_URL}')

# Create the database if it does not exist
with engine.connect() as connection:
    connection.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}"))

# Create the engine with the specific database
DATABASE_URL = f'mysql+mysqlconnector://{DB_USERNAME}:{DB_PASSWORD}@{DB_URL}/{DB_NAME}'
engine = create_engine(DATABASE_URL)
Base = declarative_base()

def read_pdf(file):
    """Read the PDF file and return a list of pages."""
    reader = PdfReader(file)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text())
    return pages

def chunk_by_pages(pages, start_page=0, end_page=None):
    """Chunk the text based on specified page range."""
    if end_page is None:
        end_page = len(pages)
    return pages[start_page:end_page]

# def chunk_text(text, max_length=3000):
#     """Split text into smaller chunks that fit within the model's token limit."""
#     chunks = []
#     while len(text) > max_length:
#         split_index = text.rfind(' ', 0, max_length)
#         if split_index == -1:
#             split_index = max_length
#         chunks.append(text[:split_index])
#         text = text[split_index:].strip()
#     if text:
#         chunks.append(text)
#     return chunks

# Define the database model
class Question(Base):
    __tablename__ = 'questions'
    id = Column(Integer, primary_key=True)
    type = Column(String(50))
    content = Column(String(255))
    difficulty = Column(String(50))
    created_at = Column(Date)

# Create tables
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# OpenAI API setup
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Read PDF content
    try:
        pages = read_pdf(file)
    except Exception as e:
        return jsonify({"error": "Failed to read PDF: " + str(e)}), 500

    # Split text into manageable chunks
    chunks = chunk_by_pages(pages, start_page=17, end_page=45)  # Adjust max_length as needed
    
    # for chunk in chunks :
    #     try:
    #         response = openai.chat.completions.create(
    #             model="gpt-3.5-turbo",
    #             messages=[
    #                 {"role": "user", "content": f"Hasilkan 10 pertanyaan dari teks berikut:\n{chunk}"}
    #             ]
    #         )
    #         questions_dict = response.model_dump()
    #         questions = questions_dict['choices'][0]['message']['content'].strip().split('\n')
    #         questions_real = response.choices[0].message.content
            
    #         print(questions_real)
    #         # print(questions)
            
    #     except Exception as e:
    #         return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500
    
    all_questions = []
    
    for chunk in chunks:
        try:
            # Join the chunked pages into a single text block
            chunk_text = "\n".join(chunk)
            
            # Generate multiple choice questions
            mc_response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": f"Hasilkan 1 pertanyaan pilihan ganda dari teks berikut:\n{chunk_text}"}
                ]
            )
            logging.info(f"Multiple Choice Response: {mc_response}")  # Log the response

            mc_questions = mc_response.choices[0].message.content.strip().split('\n')
            for question in mc_questions:
                # Assuming the format is "Question? A) Option1 B) Option2 C) Option3 D) Option4"
                parts = question.split(' ')
                answer = parts[0]  # Extract the answer (this is a simplification)
                all_questions.append({"type": "multiple_choice", "content": question, "answer": answer})
                logging.info(f"Generated MC Question: {question}, Answer: {answer}")  # Log the question and answer

            # Generate true/false questions
            tf_response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": f"Hasilkan 1 pertanyaan benar atau salah dari teks berikut:\n{chunk_text}"}
                ]
            )
            logging.info(f"True/False Response: {tf_response}")  # Log the response
            tf_questions = tf_response.choices[0].message.content.strip().split('\n')
            for question in tf_questions:
                all_questions.append({"type": "true_false", "content": question, "answer": "True/False"})
                logging.info(f"Generated TF Question: {question}, Answer: True/False")  # Log the question


            # Generate fill-in-the-blank questions
            fb_response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": f"Hasilkan 1 pertanyaan isian dari pertanyaan berikut:\n{chunk_text}"}
                ]
            )
            logging.info(f"Fill-in-the-Blank Response: {fb_response}")  # Log the response
            fb_questions = fb_response.choices[0].message.content.strip().split('\n')
            for question in fb_questions:
                answer = "expected_answer"  # You would need to extract the expected answer from the question
                all_questions.append({"type": "fill_blank", "content": question, "answer": answer})
                logging.info(f"Generated FB Question: {question}, Answer: {answer}")  # Log the question and answer

        except Exception as e:
            return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500

    # Store questions in the database
    try:
        for question in all_questions:
            new_question = Question(content=question, type='general', difficulty='medium', created_at=datetime.now())
            session.add(new_question)
        session.commit()
    except Exception as e:
        session.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    return jsonify({"message": "Questions generated and stored successfully!", "questions": all_questions}), 200

if __name__ == '__main__':
    app.run(debug=True)
