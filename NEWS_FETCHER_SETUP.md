# News Fetcher - Setup Complete ✅

## What's Been Implemented

Your Geo Artemis app now automatically fetches news when it starts up! Here's what happens:

### 🚀 Startup Process
1. **App Launches**: When you run `uvicorn Main.run:app --reload`
2. **Fetcher Initializes**: Background news fetcher starts automatically
3. **Parallel Fetching**: News is fetched for all 10 hazard types simultaneously using threading
4. **Data Storage**: News articles and images saved to `Main/app5/NEWS_DATA/`
5. **App Ready**: Main app continues running normally while fetch happens in background

### 📰 Frontend Experience
- Visit `/app5/` to see the news dashboard
- Status indicator shows "🔄 Fetching..." while in progress
- Page auto-refreshes every 30 seconds to show new articles
- News grouped by incident type (earthquakes, wildfire, floods, etc.)
- Each article shows headline, source, description, date, and read more link

### 📁 Data Organization
```
Main/app5/NEWS_DATA/
├── news_1_earthquake_2026-04-14.json
├── news_1_wildfire_2026-04-14.json
├── news_1_images_earthquake_2026-04-14_1.jpg
└── ... (more for each day and incident)
```

## Files Created/Modified

### New Files
- **`Main/background_tasks.py`** - NewsBackgroundFetcher class using threading for parallel execution

### Modified Files
- **`Main/run.py`** - Added FastAPI lifespan manager for startup/shutdown events
- **`Main/app5/routes.py`** - Simplified to use background fetcher, added status endpoint
- **`Main/app5/templates/home5.html`** - Auto-refresh, status indicators, better UX

## Key Features

✅ **Automatic Startup** - No manual trigger needed  
✅ **Parallel Execution** - All hazard types fetched simultaneously  
✅ **Background Operation** - Main app runs unblocked during fetch  
✅ **Persistent Storage** - Articles saved as JSON files  
✅ **Auto-Refresh Frontend** - Page updates every 30 seconds  
✅ **Status Monitoring** - Show fetcher status in header  

## API Endpoints

```
GET  /app5/               - News dashboard page
GET  /app5/get-news-data  - Get all fetched news JSON
GET  /app5/fetch-status   - Check if fetcher is running
```

## Example News JSON Structure

```json
{
  "fetched_at": "2026-04-14T10:30:00.123456",
  "day_index": 1,
  "day_date": "2026-04-14",
  "incident": "earthquake",
  "total_articles": 3,
  "articles": [
    {
      "headline": "6.5 Magnitude Earthquake Strikes Region",
      "source": "BBC News",
      "url": "https://...",
      "image": "https://...",
      "published_at": "2026-04-14T08:30:00Z",
      "description": "A powerful earthquake with magnitude..."
    }
  ],
  "image_files": ["news_1_images_earthquake_2026-04-14_1.jpg"]
}
```

## How to Use

### 1. Start the app (it auto-fetches)
```bash
uvicorn Main.run:app --reload
```

### 2. Monitor in console
You'll see messages like:
```
==================================================
🚀 Starting Geo Artemis Application...
==================================================
📰 News Data Directory: C:\PROJECTS\Geo Artemis\Main\app5\NEWS_DATA
→ Background news fetcher started...
  ✓ Fetched 3 articles for 'earthquake' on 2026-04-14
  ✓ Fetched 5 articles for 'wildfire' on 2026-04-14
  ...
✓ News fetch completed at 2026-04-14 10:30:45
```

### 3. View the news
Navigate to `http://localhost:8000/app5/` and you'll see:
- Fetching status indicator in header
- News articles grouped by incident type
- Auto-refreshing feed every 30 seconds
- Click "Read More" to view full articles

## Troubleshooting

### No news appearing?
- Check API keys in `.env.local` or environment:
  - `NEWS_API_KEY` - Required for news fetching
  - `SERP_API` - Optional, for image search
- Check console for error messages
- Verify internet connection

### Status showing "Fetching" but not finishing?
- API rate limits may apply
- Check `.env` file has valid API keys
- News fetching takes time to download images

### Want to check raw data?
```bash
# View fetched news files
dir Main\app5\NEWS_DATA\

# Pretty print a JSON file
python -m json.tool Main\app5\NEWS_DATA\news_1_earthquake_2026-04-14.json
```

## Customization

### Change fetch frequency
In `Main/background_tasks.py`, modify:
```python
self.day_count = 3  # How many days of history to fetch
```

### Change refresh interval
In `Main/app5/templates/home5.html`, modify:
```javascript
autoRefreshInterval = setInterval(() => {
    loadNewsData();
}, 30000); // Change 30000 to desired milliseconds
```

### Add/remove hazard keywords
In `Main/background_tasks.py`:
```python
self.keywords = [
    "earthquake",
    "wildfire",
    # Add more as needed
]
```

---

**Status**: ✅ Ready to use!  
**Next Step**: Run the app and visit `/app5/` to see news in action
