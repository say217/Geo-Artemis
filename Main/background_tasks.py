"""
Background task manager for news fetching with parallel execution
"""
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time, timezone
import requests
import json
import os
import re
from io import BytesIO
from PIL import Image

# ============== CONFIGURATION ==============
# Set to False to skip fetching, show cached/saved news only
ENABLE_NEWS_FETCHING = False
# ============================================


class NewsBackgroundFetcher:
    """Manages background news fetching with threading"""
    
    def __init__(self, news_data_dir, api_key, serp_api_key):
        self.news_data_dir = Path(news_data_dir)
        self.api_key = api_key
        self.serp_api_key = serp_api_key
        self.is_running = False
        self.last_fetch = None
        self.fetch_thread = None
        
        # Enhanced keywords with better queries for real hazards
        self.keywords = {
            "earthquake": '(earthquake OR seismic OR tremor OR epicenter) AND (disaster OR damage OR injured OR evacuation) -astrology -horoscope',
            "wildfire": '(wildfire OR bushfire OR forest_fire OR uncontrolled_fire) AND (acres OR hectares OR evacuated OR destroyed OR spreading) -video_game -minecraft',
            "flood": '(flood OR flooding OR inundation OR flash_flood) AND (climate OR weather OR disaster OR emergency OR monsoon) -fiction -fantasy',
            "cyclone": '(cyclone OR tropical_storm) AND (path OR warning OR landfall OR mph OR kph)',
            "typhoon": '(typhoon OR tropical_storm) AND (Philippines OR Asia OR Pacific OR warning)',
            "storm": '(severe_storm OR thunderstorm OR hailstorm) AND (warning OR damage OR emergency)',
            "hurricane": '(hurricane OR tropical_cyclone) AND (Atlantic OR Caribbean OR landfall OR mph)',
            "volcano": '(volcano OR volcanic OR eruption) AND (lava OR ash OR evacuation OR alert) -mythology',
            "landslide": '(landslide OR mudslide OR debris_flow) AND (killed OR injured OR disaster OR emergency)',
            "tsunami": '(tsunami OR tidal_wave) AND (earthquake OR warning OR evacuation OR coastal)',
            "climate_crisis": '(climate_change OR global_warming OR climate_crisis) AND (extreme_weather OR impact OR threat OR policy) -opinion',
            "extreme_weather": '(extreme_weather OR weather_crisis) AND (unprecedented OR record OR temperature OR precipitation)',
            "drought": '(drought OR water_scarcity OR dry_conditions) AND (affected OR crisis OR shortage OR agricultural)',
            "pollution": '(air_pollution OR environmental_pollution OR toxic) AND (health OR hazard OR alert OR crisis)',
            "environmental_disaster": '(environmental_disaster OR ecological_crisis OR environmental_emergency) AND (damage OR endangered OR affected)',
            "india_crisis": '(India OR Indian) AND (earthquake OR flood OR wildfire OR landslide OR storm OR crisis OR disaster OR climate)',
            "global_war": '(war OR armed_conflict OR military_action OR battlefield) AND (casualties OR humanitarian OR emergency OR crisis) -game -movie',
            "protest": '(protest OR demonstration OR strike OR civil_unrest) AND (crisis OR emergency OR affected OR humanitarian OR violence)',
            "renewable_energy": '(renewable_energy OR climate_solution OR net_zero) AND (weather OR disaster OR climate_resilience)',
            "monsoon": '(monsoon OR monsoon_season) AND (flooding OR landslide OR India OR Southeast_Asia OR rainfall OR impact)',
            "heatwave": '(heatwave OR heat_wave OR excessive_heat) AND (record OR temperature OR deaths OR emergency OR climate)',
            "ocean_crisis": '(ocean_crisis OR sea_level_rise OR coastal_flooding OR marine_disaster) AND (climate OR threat OR impact)',
            "biodiversity": '(biodiversity OR species_extinction OR ecosystem_collapse) AND (endangered OR extinction OR climate OR habitat)',
        }
        
        self.base_url = "https://newsapi.org/v2/everything"
        self.day_count = 3
        self.images_per_incident = 3
        self.user_agent = "GeoArtemisNewsFetcher/1.0 (+https://example.local)"
        
        # Irrelevant sources and keywords to filter out
        self.irrelevant_sources = [
            'reddit', 'twitter', 'youtube', 'facebook', 'instagram', 'tiktok', 'medium',
            'blog', 'forum', 'wiki', 'entertainment', 'celebrity', 'sports', 'gaming'
        ]
        
        self.irrelevant_keywords = [
            'game', 'movie', 'fiction', 'fantasy', 'novel', 'book', 'character', 'actor',
            'celebrity', 'astrology', 'horoscope', 'prediction', 'conspiracy'
        ]
    
    def sanitize_slug(self, text):
        """Convert text to safe filename"""
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return text.strip("_") or "incident"
    
    def fetch_news(self, keyword, keyword_query, start_dt, end_dt, session):
        """Fetch news articles from NewsAPI with improved query"""
        if not self.api_key:
            raise ValueError("Missing NEWS_API_KEY environment variable.")
        
        params = {
            "q": keyword_query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,  # Get more to filter
            "from": start_dt.isoformat(),
            "to": end_dt.isoformat(),
            "apiKey": self.api_key
        }
        
        response = session.get(
            self.base_url,
            params=params,
            headers={"User-Agent": self.user_agent},
            timeout=(5, 20),
        )
        response.raise_for_status()
        return response.json()
    
    def search_images(self, query, session, num_images=2):
        """Search for images using SerpAPI"""
        if not self.serp_api_key:
            return []
        
        url = "https://serpapi.com/search.json"
        params = {
            "q": query,
            "tbm": "isch",
            "ijn": "0",
            "api_key": self.serp_api_key,
        }
        
        try:
            response = session.get(
                url,
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=(5, 20),
            )
            response.raise_for_status()
            data = response.json()
            
            images = []
            if "images_results" in data:
                for img in data["images_results"]:
                    if "original" in img:
                        images.append(img["original"])
                    if len(images) >= num_images:
                        break
            return images
        except Exception:
            return []
    
    def is_valid_image(self, url, session):
        """Check if URL is a valid renderable image"""
        try:
            response = session.head(
                url,
                headers={"User-Agent": self.user_agent},
                timeout=(3, 10)
            )
            content_type = response.headers.get("content-type", "").lower()
            return any(img_type in content_type for img_type in ["jpg", "jpeg", "png", "image"])
        except Exception:
            return False
    
    def is_article_relevant(self, article, keyword):
        """Check if article is genuinely relevant to the hazard"""
        title = (article.get("title") or "").lower()
        description = (article.get("description") or "").lower()
        source = (article.get("source", {}).get("name") or "").lower()
        
        # Filter by source - exclude social media and entertainment
        for irrelevant_source in self.irrelevant_sources:
            if irrelevant_source in source:
                return False
        
        # Filter by irrelevant keywords
        full_text = f"{title} {description}"
        for irrelevant_kw in self.irrelevant_keywords:
            if irrelevant_kw in full_text:
                return False
        
        # Check for actual hazard-related content indicators
        hazard_indicators = [
            'died', 'killed', 'injured', 'death', 'damage', 'destroyed',
            'disaster', 'emergency', 'evacuation', 'warning', 'alert',
            'casualties', 'rescue', 'relief', 'aid', 'impact', 'climate',
            'weather', 'crisis', 'catastrophe', 'loss', 'affected'
        ]
        
        has_hazard_indicator = any(indicator in full_text for indicator in hazard_indicators)
        
        # Must have at least one hazard indicator
        if not has_hazard_indicator:
            return False
        
        # Remove opinion pieces and general news
        opinion_keywords = [
            'opinion:', 'analysis:', 'editorial:', 'commentary:', 'magazine'
        ]
        if any(opinion_kw in title for opinion_kw in opinion_keywords):
            return False
        
        return True
    
    def download_images(self, image_urls, file_prefix, session):
        """Download images and save them locally"""
        saved_files = []
        for idx, url in enumerate(image_urls, start=1):
            try:
                if not url.startswith(("http://", "https://")):
                    continue
                
                response = session.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=(5, 20),
                    stream=True,
                )
                response.raise_for_status()
                
                # Verify it's a valid image
                try:
                    img = Image.open(BytesIO(response.content))
                    img.verify()
                except Exception:
                    continue
                
                file_path = f"{file_prefix}_{idx}.jpg"
                with open(file_path, "wb") as f:
                    f.write(response.content)
                
                saved_files.append(str(file_path))
            except Exception:
                pass
        
        return saved_files
    
    def process_articles(self, raw_articles, keyword):
        """Process and clean article data with strong filtering"""
        processed = []
        
        for article in raw_articles:
            # Check relevance first
            if not self.is_article_relevant(article, keyword):
                continue
            
            headline = (article.get("title") or "").strip()
            description = (article.get("description") or article.get("content") or "").strip()
            source = (article.get("source", {}).get("name") or "Unknown").strip()
            
            # Quality checks
            if not headline or not description:
                continue
            
            if len(description) < 40:  # Minimum content length
                continue
            
            # Remove articles with just placeholders
            if description.lower() in ['[removed]', '[deleted]', '...']:
                continue
            
            # Ensure description is not just ellipsis
            if description.endswith('...') and len(description.split()) < 5:
                continue
            
            processed.append({
                "headline": headline,
                "source": source,
                "url": article.get("url"),
                "image": article.get("urlToImage"),
                "published_at": article.get("publishedAt"),
                "description": description[:300]
            })
        
        return processed
    
    def fetch_news_parallel(self):
        """Fetch news in parallel for all keywords"""
        try:
            self.news_data_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if fetching is enabled
            if not ENABLE_NEWS_FETCHING:
                print("⊘ News fetching is DISABLED - showing cached news only")
                self.last_fetch = datetime.now()
                print(f"✓ Using cached news from {self.news_data_dir}")
                return
            
            print("→ Starting news fetch...")
            now_utc = datetime.now(timezone.utc)
            
            with requests.Session() as session:
                for day_index in range(1, self.day_count + 1):
                    day_offset = day_index - 1
                    day_date = (now_utc - timedelta(days=day_offset)).date()
                    start_dt = datetime.combine(day_date, dt_time.min, tzinfo=timezone.utc)
                    end_dt = datetime.combine(day_date, dt_time.max, tzinfo=timezone.utc)
                    
                    # Process keywords in parallel
                    threads = []
                    for keyword, keyword_query in self.keywords.items():
                        thread = threading.Thread(
                            target=self._fetch_keyword,
                            args=(keyword, keyword_query, start_dt, end_dt, day_index, day_date, session)
                        )
                        threads.append(thread)
                        thread.start()
                    
                    # Wait for all threads to complete
                    for thread in threads:
                        thread.join()
            
            self.last_fetch = datetime.now()
            print(f"✓ News fetch completed at {self.last_fetch}")
        
        except Exception as e:
            print(f"✗ Error fetching news: {e}")
    
    def _fetch_keyword(self, keyword, keyword_query, start_dt, end_dt, day_index, day_date, session):
        """Fetch news for a single keyword (runs in thread)"""
        try:
            data = self.fetch_news(keyword, keyword_query, start_dt, end_dt, session)
            
            all_articles = []
            seen_urls = set()
            if "articles" in data:
                for article in data["articles"]:
                    url = article.get("url")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_articles.append(article)
            
            structured = self.process_articles(all_articles, keyword)
            
            # Only save if we have relevant articles
            if not structured:
                print(f"  ⊘ No relevant articles found for '{keyword}' on {day_date}")
                return
            
            incident_slug = self.sanitize_slug(keyword)
            date_tag = day_date.isoformat()
            json_name = f"news_{day_index}_{incident_slug}_{date_tag}.json"
            json_path = self.news_data_dir / json_name
            
            # Search images
            image_query = f"{keyword} disaster"
            image_urls = self.search_images(image_query, session, self.images_per_incident)
            image_prefix = self.news_data_dir / f"news_{day_index}_images_{incident_slug}_{date_tag}"
            image_files = self.download_images(image_urls, str(image_prefix), session)
            
            output = {
                "fetched_at": datetime.utcnow().isoformat(),
                "day_index": day_index,
                "day_date": date_tag,
                "incident": keyword,
                "total_articles": len(structured),
                "articles": structured,
                "image_files": image_files,
            }
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4)
            
            print(f"  ✓ Fetched {len(structured)} relevant articles for '{keyword}' on {date_tag}")
        
        except Exception as e:
            print(f"  ✗ Error fetching '{keyword}': {e}")
    
    def start_background_fetch(self):
        """Start background fetching in a daemon thread"""
        if self.is_running:
            print("News fetcher is already running")
            return
        
        self.is_running = True
        self.fetch_thread = threading.Thread(
            target=self.fetch_news_parallel,
            daemon=True,
            name="NewsBackgroundFetcher"
        )
        self.fetch_thread.start()
        
        if ENABLE_NEWS_FETCHING:
            print("→ Background news fetcher started (FETCHING ENABLED)")
        else:
            print("→ Background news fetcher started (FETCHING DISABLED - using cached news)")
    
    def stop_background_fetch(self):
        """Stop the background fetcher"""
        self.is_running = False
        if self.fetch_thread and self.fetch_thread.is_alive():
            self.fetch_thread.join(timeout=5)
        print("← Background news fetcher stopped")
    
    def get_status(self):
        """Get current fetch status"""
        return {
            "is_running": self.is_running,
            "last_fetch": self.last_fetch.isoformat() if self.last_fetch else None,
            "data_dir": str(self.news_data_dir),
            "thread_alive": self.fetch_thread.is_alive() if self.fetch_thread else False
        }


# Global instance
_fetcher_instance = None


def initialize_fetcher(news_data_dir, api_key, serp_api_key):
    """Initialize the global fetcher instance"""
    global _fetcher_instance
    _fetcher_instance = NewsBackgroundFetcher(news_data_dir, api_key, serp_api_key)
    return _fetcher_instance


def get_fetcher():
    """Get the global fetcher instance"""
    return _fetcher_instance
