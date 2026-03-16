# app/ai.py
import joblib
from transformers import pipeline
from sentence_transformers import SentenceTransformer 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF
import nltk
from nltk.corpus import stopwords
import warnings
import os
import numpy as np
from collections import Counter
import re
import google.generativeai as genai

# --- Global Variables ---
toxicity_model = None
predictive_pipeline = None
embedding_model = None 
zero_shot_classifier = None
summarizer = None

def init_ai():
    global toxicity_model, predictive_pipeline, embedding_model, zero_shot_classifier, summarizer
    print("AI models loading...")
    try: toxicity_model = pipeline("text-classification", model="unitary/toxic-bert")
    except Exception as e: print(f"Error loading toxicity: {e}")
    try: predictive_pipeline = pipeline("text-classification", model="nlptown/bert-base-multilingual-uncased-sentiment")
    except Exception as e: print(f"Error loading predictive: {e}")
    try: embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    except Exception as e: print(f"Error loading embedding model: {e}")
    try: zero_shot_classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
    except Exception as e: print(f"Error loading zero-shot: {e}")
    # LOAD SUMMARIZER
    try: summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
    except Exception as e: print(f"Error loading summarizer: {e}")

# NLTK Setup
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    print("Downloading NLTK data...")
    nltk.download('stopwords')
    nltk.download('averaged_perceptron_tagger')
    nltk.download('punkt')
    nltk.download('averaged_perceptron_tagger_eng')

# --- Helper Functions ---

def get_topics(reviews, n_topics=3, n_words=3):
    if not reviews or len(reviews) < n_topics: return []
    stop_words = list(stopwords.words('english'))
    vectorizer = TfidfVectorizer(max_df=0.95, min_df=2, stop_words=stop_words)
    try:
        tfidf = vectorizer.fit_transform(reviews)
    except ValueError: return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nmf = NMF(n_components=n_topics, random_state=1, l1_ratio=0.5).fit(tfidf)
    feature_names = vectorizer.get_feature_names_out()
    topics = []
    for topic_idx, topic in enumerate(nmf.components_):
        top_words = [feature_names[i] for i in topic.argsort()[:-n_words - 1:-1]]
        topics.append(", ".join(top_words))
    return topics

def get_word_cloud_data(reviews):
    if not reviews: return []
    combined_text = " ".join(reviews).lower()
    tokens = nltk.word_tokenize(combined_text)
    stop_words = set(stopwords.words('english'))
    context_stops = {'course', 'class', 'professor', 'teacher', 'student', 'lecture'}
    stop_words.update(context_stops)
    filtered_tokens = [w for w in tokens if w.isalpha() and w not in stop_words and len(w) > 2]
    tagged = nltk.pos_tag(filtered_tokens)
    allowed_tags = {'JJ', 'JJR', 'JJS', 'NN', 'NNS'}
    meaningful_words = [word for word, tag in tagged if tag in allowed_tags]
    counts = Counter(meaningful_words)
    return [[word, count] for word, count in counts.most_common(40)]

def generate_embedding(text):
    if embedding_model and text: return embedding_model.encode(text)
    return None

def semantic_search(query, feedbacks, top_k=5):
    if not embedding_model or not query or not feedbacks: return []
    query_vector = embedding_model.encode(query)
    results = []
    for f in feedbacks:
        doc_vector = f.get_embedding()
        if doc_vector:
            doc_vector = np.array(doc_vector)
            score = np.dot(query_vector, doc_vector) / (np.linalg.norm(query_vector) * np.linalg.norm(doc_vector))
            results.append((score, f))
    results.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in results[:top_k]]

def get_professor_tags(reviews):
    if not zero_shot_classifier or not reviews: return []
    combined_text = " ".join(reviews)[:3000] 
    try:
        result = zero_shot_classifier(combined_text, ["Strict", "Humorous", "Inspiring", "Lecture-Heavy", "Practical", "Theoretical", "Easy-going"], multi_label=True)
        tags = [label for label, score in zip(result['labels'], result['scores']) if score > 0.1]
        return tags[:3] 
    except Exception: return []

# --- UPDATED GENERATE SUMMARY FUNCTION ---
def generate_summary(reviews):
    """
    Takes a list of review texts and generates a summary using the loaded pipeline.
    """
    if not summarizer or not reviews: 
        return "Summarizer model not loaded or no reviews available."
    
    # 1. Prepare Text
    combined_text = " ".join(reviews)
    
    # 2. Limit Length (Bart model limit is usually 1024 tokens ~ 3000-4000 chars)
    if len(combined_text) > 3000:
        combined_text = combined_text[:3000]
    
    # 3. Check Minimum Length (Need enough words to summarize)
    if len(combined_text.split()) < 10: 
        return "Not enough content to generate a meaningful summary."

    try:
        # 4. Run Summarization
        summary = summarizer(combined_text, max_length=130, min_length=30, do_sample=False)
        return summary[0]['summary_text']
    except Exception as e: 
        print(f"Summarization Error: {e}")
        return "Could not generate summary due to an internal error."

# --- GLOBAL RAG (Safe Mode) ---
# --- GLOBAL RAG (Safe Mode) ---
def generate_rag_answer(context_label, question, relevant_reviews):

    api_key = os.environ.get('GEMINI_API_KEY')

    if not api_key:
        return fallback_local_answer(question, relevant_reviews)

    try:

        # Configure Gemini
        genai.configure(api_key=api_key)

        # Create the model (THIS WAS MISSING)
        model = genai.GenerativeModel('gemini-1.5-flash')

        context_text = ""

        for r in relevant_reviews:
            review_text = r.review_text if r.review_text else ""
            c_name = r.course.name if r.course else "Unknown Course"
            sentiment = r.sentiment_category if r.sentiment_category else "Neutral"

            
            context_text += f'- [Course: {c_name} | Sentiment: {sentiment}] Review: "{review_text}"\n'

        prompt = f"""
You are an expert Senior Academic Advisor.

USER QUESTION:
{question}

DATABASE REVIEWS:
{context_text}

Provide a helpful academic answer.
"""

        response = model.generate_content(prompt)

        return response.text

    except Exception as e:

        print("Gemini API Error:", e)

        return fallback_local_answer(question, relevant_reviews)
    

def general_academic_answer(question):

    prompt = f"""
            You are an AI Academic Advisor.

            Answer the student's question in a helpful academic way.

            Question:
            {question}
"""

    try:

        from transformers import pipeline

        generator = pipeline("text-generation", model="gpt2")

        response = generator(prompt, max_length=120, num_return_sequences=1)

        return response[0]['generated_text']

    except Exception as e:

        print("General AI error:", e)

        return "I couldn't generate a response right now."
    
def fallback_local_answer(question, reviews):

    if not reviews:
        return "I couldn't find enough review data to answer this question."

    text = ""

    for r in reviews[:5]:

        if r.review_text:
            text += r.review_text + ". "

    return f"""
Based on student feedback:

{text[:400]}

This summary is generated from available reviews in the database.
"""
