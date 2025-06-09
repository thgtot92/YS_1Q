import google.generativeai as genai
import os

#AIzaSyC-2aYPlx7he6pwCGmhvYYenvYGluEZApA

genai.configure(api_key=os.getenv("GOOGLE_API_KEY") or "AIzaSyC-2aYPlx7he6pwCGmhvYYenvYGluEZApA")

models = genai.list_models()
# for m in models:
#     print(f"{m.name} | supports generateContent: {'generateContent' in m.supported_generation_methods}")

def get_llm_report(prompt: str):
    model = genai.GenerativeModel("models/gemini-1.5-flash")  #버전 의문..
    response = model.generate_content(prompt)
    return response.text


def analyze_events_with_llm(events_df, matched_news_dict, stock_name):
    summaries = []
    for i, row in events_df.iterrows():
        time = row["datetime"]
        price = row["price"]
        event_type = row["event_type"]
        news_list = matched_news_dict.get(time, [])
        news_summary_text = "\n".join([f"- {n['title']}" for n in news_list]) if news_list else "- 관련 뉴스 없음"

        prompt = f"""[이벤트 기반 뉴스 분석 보고서]

📅 날짜: {time.strftime('%Y-%m-%d')}
🕒 시간: {time.strftime('%H:%M')}
📈 이벤트: {stock_name}의 주가가 {event_type} (가격: {price}원)

📰 당시 뉴스 목록:
{news_summary_text}

이 뉴스와 주가 변화의 관련성을 분석하고, 가능한 원인과 시사점을 포함하여 3~5줄로 요약해주세요.
"""
        result = get_llm_report(prompt)
        summaries.append((time.strftime('%H:%M'), event_type, result))
    return summaries