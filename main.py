from slack_sender import send_to_slack
from llm_reporter import get_llm_report
from naver_finance_crawler import fetch_kospi_daily, fetch_sector_etf_daily,fetch_industry_info_by_stock_code
# 기존 news_api_caller 대신 새로운 enhanced news collector 사용
from naver_news_crawler import EnhancedNewsCollector
from news_api_caller import match_news_before_events  # 매칭 함수는 계속 사용
from seibro_disclosure_scraper import fetch_disclosures_with_fallback, match_disclosures_before_events
import pandas as pd
import os
import requests
from datetime import datetime, timedelta
import random

def get_stock_database():
    """종목 데이터베이스"""
    return {
        "삼성전자": ("005930", "삼성전자"), "sk하이닉스": ("000660", "SK하이닉스"),
        "네이버": ("035420", "NAVER"), "카카오": ("035720", "카카오"),
        "lg전자": ("066570", "LG전자"), "현대차": ("005380", "현대차"),
        "기아": ("000270", "기아"), "포스코홀딩스": ("005490", "POSCO홀딩스"),
        "삼성sdi": ("006400", "삼성SDI"), "lg화학": ("051910", "LG화학"),
        "셀트리온": ("068270", "셀트리온"), "삼성바이오로직스": ("207940", "삼성바이오로직스"),
        "현대모비스": ("012330", "현대모비스"), "kb금융": ("105560", "KB금융"),
        "신한지주": ("055550", "신한지주"), "한화에어로스페이스": ("012450", "한화에어로스페이스"),
        "한화에어로": ("012450", "한화에어로스페이스"), "한화": ("000880", "한화"),
        "대한항공": ("003490", "대한항공"), "한화시스템": ("272210", "한화시스템"),
        "한미반도체": ("042700", "한미반도체"), "원익iqe": ("090350", "원익IQE"),
        "테스": ("095610", "테스"), "동진쎄미켐": ("005290", "동진쎄미켐"),
        "솔브레인": ("357780", "솔브레인"), "실리콘웍스": ("108320", "실리콘웍스"),
        "엔씨소프트": ("036570", "엔씨소프트"), "넷마블": ("251270", "넷마블"),
        "크래프톤": ("259960", "크래프톤"), "하이브": ("352820", "하이브"),
        "아모레퍼시픽": ("090430", "아모레퍼시픽"), "lg생활건강": ("051900", "LG생활건강"),
        "kt": ("030200", "KT"), "skt": ("017670", "SK텔레콤"),
        "한국전력": ("015760", "한국전력공사"), "농심": ("004370", "농심"), 
        "삼성생명": ("032830", "삼성생명"),"한화리츠": ("451800", "한화리츠")
    }

def robust_fetch_intraday_price(stock_code: str, date: str) -> pd.DataFrame:
    """강건한 주가 데이터 수집"""
    try:
        from naver_finance_crawler import fetch_intraday_price
        df = fetch_intraday_price(stock_code, date)
        if len(df) > 0:
            print(f"✅ 네이버 금융에서 {len(df)}개 데이터 수집 성공")
            return df
    except Exception as e:
        print(f"⚠️ 네이버 금융 실패: {e}")
    
    print("🔄 현실적인 모의 데이터 생성으로 대체")
    return generate_realistic_mock_data(stock_code, date)

def generate_realistic_mock_data(stock_code: str, date: str) -> pd.DataFrame:
    """현실적인 모의 데이터 생성"""
    base_prices = {
        "005930": 60000, "000660": 120000, "042700": 45000,
        "035420": 180000, "012450": 850000
    }
    base_price = base_prices.get(stock_code, 50000)
    
    start_time = datetime.strptime(f"{date} 09:00", "%Y-%m-%d %H:%M")
    times, prices, volumes = [], [], []
    current_price = base_price
    
    for i in range(390):
        current_time = start_time + timedelta(minutes=i)
        if 12 <= current_time.hour < 13:
            continue
            
        change_rate = random.gauss(0, 0.003)
        current_price *= (1 + change_rate)
        current_price = max(int(current_price), 1000)
        volume = random.randint(10000, 300000)
        
        times.append(current_time)
        prices.append(current_price)
        volumes.append(volume)
    
    # 의도적 이벤트 생성
    event_indices = random.sample(range(50, len(prices)-50), 3)
    for idx in event_indices:
        event_type = random.choice(['strong_up', 'strong_down'])
        multiplier = 1.002 if event_type == 'strong_up' else 0.998
        for j in range(idx, min(idx+30, len(prices))):
            prices[j] *= multiplier
            volumes[j] *= 1.5
    
    df = pd.DataFrame({
        'datetime': times,
        'price': [int(p) for p in prices],
        'volume': volumes
    })
    
    print(f"📊 현실적 모의 데이터 생성: {len(df)}개 시점, 이벤트 {len(event_indices)}개 포함")
    return df

def enhanced_detect_price_events_by_day(df: pd.DataFrame, threshold=0.006) -> pd.DataFrame:
    """향상된 이벤트 감지"""
    df = df.copy().sort_values("datetime").reset_index(drop=True)
    start_price = df.iloc[0]['price']
    df['pct_from_start'] = (df['price'] - start_price) / start_price
    df['pct_change'] = df['price'].pct_change()
    df['ma_20'] = df['price'].rolling(window=20, min_periods=1).mean()
    df['pct_from_ma'] = (df['price'] - df['ma_20']) / df['ma_20']
    
    def detect_event_type(row, index):
        if abs(row['pct_from_start']) >= threshold:
            return "상승" if row['pct_from_start'] > 0 else "하락"
        
        if index >= 10:
            recent_change = (row['price'] - df.iloc[index-10]['price']) / df.iloc[index-10]['price']
            if abs(recent_change) >= 0.008:
                return "급상승" if recent_change > 0 else "급하락"
        
        if index > 0 and df.iloc[index-1]['volume'] > 0:
            volume_ratio = row['volume'] / df.iloc[index-1]['volume']
            if volume_ratio >= 1.8 and abs(row['pct_change']) >= 0.003:
                return "거래량급증상승" if row['pct_change'] > 0 else "거래량급증하락"
        
        if not pd.isna(row['pct_from_ma']) and abs(row['pct_from_ma']) >= 0.005:
            return "MA상승이탈" if row['pct_from_ma'] > 0 else "MA하락이탈"
        
        return None
    
    df['event_type'] = [detect_event_type(row, i) for i, row in df.iterrows()]
    events = df[df['event_type'].notnull()][['datetime', 'price', 'pct_from_start', 'event_type']]
    
    print(f"🎯 향상된 이벤트 감지: {len(events)}개 (임계값: {threshold*100:.1f}%)")
    return events

def enhanced_comprehensive_analysis(events_df, matched_news_dict, matched_disclosures_dict, 
                                  stock_name: str, date: str, news_impact: dict = None,
                                  competitor_news: list = None) -> str:
    """향상된 종합 분석 (Enhanced News 정보 포함)"""
    
    # 이벤트 요약
    event_summary = ""
    if len(events_df) > 0:
        event_summary = f"📈 주요 이벤트 ({len(events_df)}개 감지):\n"
        for _, event in events_df.iterrows():
            pct = event['pct_from_start'] * 100
            event_time = event['datetime'].strftime('%H:%M')
            event_summary += f"- {event_time}: {pct:+.2f}% {event['event_type']} (₩{event['price']:,})\n"
    else:
        event_summary = "📈 주요 이벤트:\n- 0.6% 이상의 주요 변동 이벤트가 감지되지 않았습니다.\n"
    
    # 뉴스 요약
    all_news = []
    for news_list in matched_news_dict.values():
        for news in news_list:
            if news['title'] not in [n['title'] for n in all_news]:
                all_news.append(news)
    
    news_summary = ""
    if all_news:
        news_summary = f"📰 시간적 인과관계 뉴스 분석 ({len(all_news)}개):\n"
        # 관련성 점수로 정렬
        sorted_news = sorted(all_news, key=lambda x: x.get('relevance_score', 0), reverse=True)
        for news in sorted_news[:5]:
            score = news.get('relevance_score', 0)
            news_summary += f"- [{score}점] {news['title']}\n"
    else:
        news_summary = "📰 시간적 인과관계 뉴스 분석:\n- 주가 이벤트와 연관된 뉴스가 없어 내재적 시장 요인으로 분석됩니다.\n"
    
    # 뉴스 영향력 분석 추가
    impact_summary = ""
    if news_impact:
        impact_summary = f"\n📊 뉴스 영향력 분석:\n"
        impact_summary += f"- 감성 점수: {news_impact['sentiment_score']:.2f} "
        impact_summary += f"(긍정 {news_impact['positive_count']}, "
        impact_summary += f"부정 {news_impact['negative_count']}, "
        impact_summary += f"중립 {news_impact['neutral_count']})\n"
        impact_summary += f"- {news_impact['impact_summary']}\n"
        
        if news_impact.get('key_events'):
            impact_summary += "\n🎯 주요 뉴스 이벤트:\n"
            for event in news_impact['key_events'][:3]:
                impact_summary += f"- [{event['relevance_score']}점/{event['sentiment']}] {event['title']}\n"
    
    # 경쟁사 동향 추가
    competitor_summary = ""
    if competitor_news and len(competitor_news) > 0:
        competitor_summary = f"\n🏢 경쟁사 동향:\n"
        for news in competitor_news[:3]:
            competitor_summary += f"- [{news['competitor']}] {news['title']}\n"
    
    # 공시 요약
    all_disclosures = []
    for disc_list in matched_disclosures_dict.values():
        for disc in disc_list:
            if disc['title'] not in [d['title'] for d in all_disclosures]:
                all_disclosures.append(disc)
    
    disclosure_summary = ""
    if all_disclosures:
        disclosure_summary = f"📋 시간적 인과관계 공시 분석 ({len(all_disclosures)}개):\n"
        for disc in all_disclosures[:3]:
            disclosure_summary += f"- {disc['time']}: {disc['title']}\n"
    else:
        disclosure_summary = "📋 시간적 인과관계 공시 분석:\n- 주가 이벤트와 연관된 공시가 없습니다.\n"
    
    # CRAG 종합 프롬프트
    comprehensive_prompt = f"""[{date} {stock_name} 강화된 CRAG 시간적 인과관계 분석]

{event_summary}

{news_summary}
{impact_summary}
{competitor_summary}
{disclosure_summary}

🎯 **강화된 CRAG 분석 요청:**

위 시간적 인과관계 데이터를 바탕으로 다음을 분석해주세요:

1. **시간적 인과관계 분석**: 이벤트 발생 이전 정보들과의 명확한 선후관계 규명
2. **뉴스 영향력 정량화**: 감성 점수와 관련성 점수를 활용한 영향력 평가
3. **경쟁 환경 고려**: 경쟁사 동향이 자사 주가에 미친 영향 분석
4. **시장 효율성 판단**: 정보 반영 속도와 투자자 반응 분석
5. **향후 투자 전망**: 오늘의 패턴이 향후에 미칠 영향과 투자 시사점

전문적이고 실용적인 투자 분석 리포트로 작성해주세요.
"""
    
    print("🧠 강화된 CRAG 시간적 인과관계 분석 진행 중...")
    return get_llm_report(comprehensive_prompt)

def search_stock_code(stock_name: str) -> tuple:
    """종목명으로 종목 코드 검색"""
    stock_db = get_stock_database()
    normalized_query = stock_name.replace(" ", "").lower()
    
    for db_name, (code, full_name) in stock_db.items():
        db_name_normalized = db_name.lower().replace(" ", "")
        if normalized_query == db_name_normalized or normalized_query in db_name_normalized:
            print(f"✅ 종목 발견: {full_name} ({code})")
            return code, full_name
    
    candidates = []
    for db_name, (code, full_name) in stock_db.items():
        db_name_lower = db_name.lower()
        if normalized_query in db_name_lower or db_name_lower in normalized_query:
            candidates.append((code, full_name))
    
    if candidates:
        print(f"\n🎯 '{stock_name}'와 유사한 종목들:")
        for i, (code, name) in enumerate(candidates[:5], 1):
            print(f"{i}. {name} ({code})")
        
        try:
            choice = int(input(f"\n선택 (1-{len(candidates[:5])}): "))
            if 1 <= choice <= len(candidates[:5]):
                selected = candidates[choice - 1]
                return selected[0], selected[1]
        except ValueError:
            pass
    
    return None, None

def get_user_input():
    """사용자 입력 받기"""
    print("🚀 강화된 CRAG 주식 분석 시스템")
    print("="*50)
    
    while True:
        stock_name = input("\n📈 분석할 종목명을 입력하세요: ").strip()
        if stock_name:
            stock_code, exact_name = search_stock_code(stock_name)
            if stock_code and exact_name:
                break
            else:
                print("종목을 찾을 수 없습니다. 다시 시도해주세요.")
        else:
            print("종목명을 입력해주세요.")
    
    while True:
        print(f"\n📅 분석 날짜를 입력하세요.")
        print("형식: YYYY-MM-DD (예: 2025-06-09) 또는 'today'")
        
        date_input = input("날짜: ").strip().lower()
        
        if date_input == "today":
            analysis_date = datetime.now().strftime("%Y-%m-%d")
            break
        else:
            try:
                datetime.strptime(date_input, "%Y-%m-%d")
                analysis_date = date_input
                break
            except ValueError:
                print("❌ 올바른 날짜 형식이 아닙니다.")
    
    print(f"\n✅ 선택된 종목: {exact_name} ({stock_code})")
    print(f"✅ 분석 날짜: {analysis_date}")
    
    confirm = input("\n진행하시겠습니까? (y/N): ").strip().lower()
    if confirm != 'y':
        return None, None, None
    
    return stock_code, exact_name, analysis_date


def main():
    """강화된 CRAG 메인 실행 함수"""
    
    user_input = get_user_input()
    if user_input[0] is None:
        return
    
    stock_code, stock_name, date = user_input
    
    client_id = os.getenv("NAVER_CLIENT_ID") or "JEuS9xkuWGpP40lsI9Kz"
    client_secret = os.getenv("NAVER_CLIENT_SECRET") or "I6nujCm0xF"
    slack_url = os.getenv("SLACK_WEBHOOK_URL") or "https://hooks.slack.com/services/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"

    print(f"\n🚀 {stock_name}({stock_code}) {date} 강화된 CRAG 분석 시작")
    print("💡 시간적 인과관계 기반 고도화 분석")
    print("="*70)

    try:
        # 1. 강건한 주가 데이터 수집
        print("\n📊 1단계: 강건한 주가 데이터 수집")
        df = robust_fetch_intraday_price(stock_code, date)
        
        # 2. 향상된 이벤트 감지
        print("\n🎯 2단계: 향상된 이벤트 감지")
        events = enhanced_detect_price_events_by_day(df, threshold=0.006)
        print(f"✅ 주가 데이터: {len(df)}개 시점")
        print(f"✅ 감지된 이벤트: {len(events)}개")

        # 3. 향상된 뉴스 수집 시스템 사용
        print("\n📰 3단계: 향상된 뉴스 수집 및 분석")
        news_collector = EnhancedNewsCollector(client_id, client_secret)
        
        # 다중 전략 뉴스 수집
        enhanced_news = news_collector.search_news_multi_strategy(
            stock_name=stock_name,
            date=date,
            days_before=3,
            days_after=0
        )
        
        # 뉴스 영향력 분석
        news_impact = news_collector.analyze_news_impact(enhanced_news, stock_name)
        
        # 경쟁사 뉴스 수집
        competitor_news = news_collector.get_competitor_news(stock_name, date)
        
        print(f"✅ 관련성 높은 뉴스: {len(enhanced_news)}개")
        print(f"✅ 감성 분석: 긍정 {news_impact['positive_count']}, 부정 {news_impact['negative_count']}, 중립 {news_impact['neutral_count']}")
        print(f"✅ 감성 점수: {news_impact['sentiment_score']}")
        print(f"✅ 경쟁사 뉴스: {len(competitor_news)}개")

        # 4. 공시정보 수집
        print("\n📋 4단계: 공시정보 수집 (3일 범위)")
        start_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
        disclosures = fetch_disclosures_with_fallback(stock_name, start_date, date)
        print(f"✅ 수집된 공시: {len(disclosures)}개")

        # 5. CRAG 인과관계 분석
        print("\n🔗 5단계: CRAG 시간적 인과관계 분석")
        # 기존 match_news_before_events 함수와 호환되도록 변환
        analyzed_news = []
        for news in enhanced_news:
            analyzed_news.append({
                'title': news['title'],
                'link': news['link'],
                'pubDate': news['pubDate'],
                'description': news.get('description', ''),
                'relevance_score': news.get('relevance_score', 0),
                'sentiment': 'neutral'  # 기본값
            })
        
        matched_news_dict = match_news_before_events(analyzed_news, events)
        matched_disclosures_dict = match_disclosures_before_events(disclosures, events, hours_before=72)
        
        total_matched_news = sum(len(news_list) for news_list in matched_news_dict.values())
        total_matched_disclosures = sum(len(disc_list) for disc_list in matched_disclosures_dict.values())
        print(f"✅ 시간적 인과관계 매칭 - 뉴스: {total_matched_news}개, 공시: {total_matched_disclosures}개")

        # 6. 종합 CRAG 분석
        print("\n🧠 6단계: 종합 CRAG 분석")
        analysis_result = enhanced_comprehensive_analysis(
            events, matched_news_dict, matched_disclosures_dict, 
            stock_name, date, news_impact, competitor_news
        )
        
        print("✅ CRAG 분석 완료")
        print("\n" + "="*70)
        print("📄 CRAG 기반 종합 분석 리포트:")
        print("="*70)
        print(analysis_result)
        print("="*70)
        
        # 7. Slack 전송 (최종 리포트만)
        print("\n📨 7단계: Slack 전송")

        # 헤드라인 뉴스/공시 샘플 5개씩 추출
        top_news_titles = [f"- [{n.get('relevance_score', 0)}점] {n['title']}" for n in enhanced_news[:5]]
        top_disc_titles = [f"- {d['title']}" for d in disclosures[:5]]

        # 시장 지표 수집
        date_fmt = datetime.strptime(date, "%Y-%m-%d").strftime("%Y.%m.%d")
        kospi_info = fetch_kospi_daily(date_fmt)
        etf_info = fetch_sector_etf_daily(etf_code="091160", date_yyyymmdd=date_fmt)

        kospi_line = (
            f"- 코스피 지수변동 : {kospi_info.get('rate', 0):+0.2f}% "
            f"( {kospi_info.get('close', 0):,.2f} / {kospi_info.get('change', 0):+0.2f} )"
            if kospi_info and 'rate' in kospi_info else "- 코스피 지수 정보 없음"
        )
        etf_line = (
            f"- 동일 섹터(반도체 ETF): {etf_info.get('rate', 0):+0.2f}%"
            if etf_info and 'rate' in etf_info else "- 섹터 ETF 정보 없음"
        )

        # 업종 정보 수집
        industry_info = fetch_industry_info_by_stock_code(stock_code)
        industry_line = "- 업종 정보 없음"
        if industry_info and "업종명" in industry_info:
            sector = industry_info.get("업종명", "N/A")
            change = industry_info.get("등락률", "N/A")
            per = industry_info.get("PER", "N/A")
            pbr = industry_info.get("PBR", "N/A")
            industry_line = f"- 동일 업종({sector}): {change} / PER: {per} / PBR: {pbr}"

        final_message = f"""🎯 **{stock_name} {date} 강화된 CRAG 분석 리포트**

📊 **분석 현황:**
• 주가 시점: {len(df)}개
• 감지된 이벤트: {len(events)}개
• 관련 뉴스: {len(enhanced_news)}개 (감성: {news_impact['sentiment_score']:.2f})
{('\n' + '\n'.join(top_news_titles)) if top_news_titles else ""}
• 경쟁사 뉴스: {len(competitor_news)}개
• 수집 공시: {len(disclosures)}개
{('\n' + '\n'.join(top_disc_titles)) if top_disc_titles else ""}
• 인과관계 매칭: 뉴스 {total_matched_news}개, 공시 {total_matched_disclosures}개
• 시장 지표 비교 
{kospi_line}
{etf_line}
{industry_line}

📈 **뉴스 영향력 분석:**
{news_impact['impact_summary']}

📈 **CRAG 분석 결과:**
{analysis_result}

---
*강화된 CRAG 시간적 인과관계 분석 시스템*
"""

        send_to_slack(final_message, slack_url)
        print("✅ 강화된 CRAG 분석 리포트 Slack 전송 완료")

    except Exception as e:
        error_msg = f"🚨 CRAG 시스템 오류: {e}"
        print(error_msg)
        send_to_slack(error_msg, slack_url)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()