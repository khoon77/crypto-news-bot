import os
import requests
import json
from datetime import datetime, timedelta
import feedparser
import logging
from typing import List, Dict, Set
import hashlib
import sqlite3
import re
from urllib.parse import urlparse

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('crypto_news.log')
    ]
)

class CryptoNewsTelegramBot:
    def __init__(self):
        # 환경변수에서 설정값 읽기
        self.telegram_bot_token = os.getenv('8046651654:AAHCU-LlMq5wn5522SXq1aZm1GDobcjwkWc')
        self.telegram_chat_id = os.getenv('1023578818')
        self.newsapi_key = os.getenv('NEWSAPI_KEY', '')
        
        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID 환경변수를 설정해주세요!")
        
        # 암호화폐 관련 키워드
        self.crypto_keywords = [
            'bitcoin', 'btc', 'ethereum', 'eth', 'altcoin', 'cryptocurrency', 
            'crypto', 'blockchain', 'defi', 'nft', 'solana', 'cardano', 'ada',
            'ripple', 'xrp', 'binance', 'bnb', 'dogecoin', 'doge', 'shiba',
            'polygon', 'matic', 'chainlink', 'link', 'avalanche', 'avax',
            'polkadot', 'dot', 'litecoin', 'ltc', 'uniswap', 'uni'
        ]
        
        # 암호화폐 뉴스 RSS 피드
        self.crypto_rss_feeds = [
            "https://cointelegraph.com/rss",
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cryptonews.com/news/feed/",
            "https://decrypt.co/feed",
            "https://bitcoinmagazine.com/.rss/full/",
            "https://u.today/rss",
            "https://cryptopotato.com/feed/",
            "https://www.crypto-news-flash.com/feed/",
            "https://coinjournal.net/feed/",
            "https://news.bitcoin.com/feed/"
        ]
        
        # 데이터베이스 경로 설정 (GitHub Actions 환경용)
        self.db_path = os.path.join('data', 'crypto_news.db')
        os.makedirs('data', exist_ok=True)
        self.init_database()
        
    def init_database(self):
        """SQLite 데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_hash TEXT UNIQUE,
                title TEXT,
                link TEXT,
                sent_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 7일 이상 된 기록 삭제
        week_ago = datetime.now() - timedelta(days=7)
        cursor.execute('DELETE FROM sent_articles WHERE sent_time < ?', (week_ago,))
        
        conn.commit()
        conn.close()
        logging.info(f"데이터베이스 초기화 완료: {self.db_path}")
    
    def get_article_hash(self, title: str, link: str) -> str:
        """기사 고유 해시 생성"""
        content = f"{title}{link}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def is_article_sent(self, article_hash: str) -> bool:
        """기사가 이미 전송되었는지 확인"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM sent_articles WHERE article_hash = ?', (article_hash,))
        result = cursor.fetchone() is not None
        
        conn.close()
        return result
    
    def mark_article_as_sent(self, article_hash: str, title: str, link: str):
        """기사를 전송됨으로 표시"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO sent_articles (article_hash, title, link) VALUES (?, ?, ?)',
                (article_hash, title, link)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        
        conn.close()
    
    def contains_crypto_keywords(self, text: str) -> bool:
        """텍스트에 암호화폐 키워드가 포함되어 있는지 확인"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.crypto_keywords)
    
    def send_telegram_message(self, message: str):
        """텔레그램으로 메시지 전송"""
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        
        data = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logging.info("텔레그램 메시지 전송 성공")
                return True
            else:
                logging.error(f"텔레그램 전송 실패: {response.status_code}")
                return False
        except Exception as e:
            logging.error(f"텔레그램 전송 중 오류: {e}")
            return False
    
    def get_crypto_news_from_rss(self) -> List[Dict]:
        """RSS 피드에서 암호화폐 뉴스 가져오기"""
        all_articles = []
        current_time = datetime.now()
        four_hours_ago = current_time - timedelta(hours=4)
        
        for rss_url in self.crypto_rss_feeds:
            try:
                logging.info(f"RSS 피드 확인 중: {rss_url}")
                feed = feedparser.parse(rss_url)
                
                source_name = self.extract_source_name(rss_url, feed)
                
                for entry in feed.entries:
                    title = entry.get('title', '')
                    summary = entry.get('summary', '')
                    
                    if self.contains_crypto_keywords(title + ' ' + summary):
                        pub_date = self.parse_publish_date(entry)
                        
                        if pub_date and pub_date > four_hours_ago:
                            article = {
                                'title': title,
                                'link': entry.get('link', ''),
                                'source': source_name,
                                'published': pub_date.strftime('%Y-%m-%d %H:%M'),
                                'summary': summary[:200] + '...' if len(summary) > 200 else summary
                            }
                            
                            article_hash = self.get_article_hash(title, article['link'])
                            if not self.is_article_sent(article_hash):
                                article['hash'] = article_hash
                                all_articles.append(article)
                                
            except Exception as e:
                logging.error(f"RSS 피드 파싱 오류 ({rss_url}): {e}")
                continue
        
        all_articles.sort(key=lambda x: x['published'], reverse=True)
        return all_articles[:10]
    
    def extract_source_name(self, rss_url: str, feed) -> str:
        """RSS URL에서 소스 이름 추출"""
        if hasattr(feed, 'feed') and hasattr(feed.feed, 'title'):
            return feed.feed.title
        
        parsed_url = urlparse(rss_url)
        domain = parsed_url.netloc.replace('www.', '')
        
        domain_mapping = {
            'cointelegraph.com': 'Cointelegraph',
            'coindesk.com': 'CoinDesk',
            'cryptonews.com': 'CryptoNews',
            'decrypt.co': 'Decrypt',
            'bitcoinmagazine.com': 'Bitcoin Magazine',
            'u.today': 'U.Today',
            'cryptopotato.com': 'CryptoPotato',
            'crypto-news-flash.com': 'Crypto News Flash',
            'coinjournal.net': 'Coin Journal',
            'news.bitcoin.com': 'Bitcoin News'
        }
        
        return domain_mapping.get(domain, domain.title())
    
    def parse_publish_date(self, entry) -> datetime:
        """RSS 엔트리에서 발행 날짜 파싱"""
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                return datetime(*entry.published_parsed[:6])
            elif hasattr(entry, 'published'):
                parsed_time = feedparser._parse_date(entry.published)
                if parsed_time:
                    return datetime(*parsed_time[:6])
        except Exception as e:
            logging.error(f"날짜 파싱 오류: {e}")
        
        return datetime.now()
    
    def format_crypto_news_message(self, articles: List[Dict]) -> str:
        """암호화폐 뉴스를 텔레그램 메시지 형태로 포맷"""
        if not articles:
            return ""
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        message = f"🚀 <b>암호화폐 뉴스 알림</b> ({current_time})\n\n"
        
        for i, article in enumerate(articles, 1):
            title = article['title']
            if len(title) > 80:
                title = title[:80] + "..."
            
            title = self.highlight_crypto_keywords(title)
            
            message += f"📰 <a href='{article['link']}'>{title}</a>\n"
            message += f"📍 {article['source']} | ⏰ {article['published']}\n\n"
            
            if len(message) > 3500:
                break
        
        return message
    
    def highlight_crypto_keywords(self, text: str) -> str:
        """텍스트에서 암호화폐 키워드를 볼드로 강조"""
        highlighted_text = text
        for keyword in ['Bitcoin', 'BTC', 'Ethereum', 'ETH', 'crypto', 'cryptocurrency']:
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            highlighted_text = pattern.sub(f'<b>{keyword}</b>', highlighted_text)
        return highlighted_text
    
    def run_once(self):
        """한 번만 실행하는 메서드 (GitHub Actions용)"""
        logging.info("암호화폐 뉴스 봇 시작 (GitHub Actions)")
        
        articles = self.get_crypto_news_from_rss()
        
        if articles:
            message = self.format_crypto_news_message(articles)
            
            if message and self.send_telegram_message(message):
                for article in articles:
                    self.mark_article_as_sent(
                        article['hash'], 
                        article['title'], 
                        article['link']
                    )
                
                logging.info(f"암호화폐 뉴스 {len(articles)}개 전송 완료")
            else:
                logging.warning("전송할 뉴스가 없거나 전송 실패")
        else:
            logging.info("새로운 암호화폐 뉴스가 없습니다")

if __name__ == "__main__":
    try:
        bot = CryptoNewsTelegramBot()
        bot.run_once()
    except Exception as e:
        logging.error(f"봇 실행 중 오류 발생: {e}")
        exit(1)