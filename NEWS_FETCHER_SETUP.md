# News Fetcher - Architecture & Setup ✅

## Current Architecture

The news fetching system in Geo Artemis has been optimized for reliability, API quota conservation, and continuous operation.

### 🚀 Startup & Periodic Sync
1. **Initial Boot**: When `run.py` starts, it triggers a global data synchronization task.
2. **6-Hour Freshness Rule**: The system checks if the local news cache is "fresh" (less than 6 hours old). If fresh, it skips external API calls to save quota.
3. **Background Sync Loop**: A persistent background task in `run.py` re-checks all data sources every 30 minutes. If the app runs for more than 6 hours, it automatically refreshes the data.

### 📰 Data Sources & Fetching Logic
- **Primary Logic**: Located in `Main/app3/routes.py`.
- **API Used**: NewsAPI (via `NEWS_API_KEY_GLOB`).
- **Throttling**: To avoid 429 Rate Limit errors (especially on free tier), the fetcher waits 7 seconds between each category request.
- **Categories**:
    - `all` (Merged hazard/conflict query)
    - `wildfire`
    - `earthquake`
    - `war` (Geopolitics & Military conflict)
    - `protest` (Civil unrest)
    - `pollution` (Air quality & Smog)

### 📁 Data Organization
All fetched news is stored in a centralized location to be shared across the platform:
```
Main/app3/Glob_data/
├── all.json
├── wildfire.json
├── earthquake.json
├── war.json
├── protest.json
└── pollution.json
```
**JSON Structure**:
```json
{
  "saved_at": "2026-04-26T15:00:00Z",
  "data": {
    "news": [
      {
        "type": "wildfire",
        "title": "...",
        "description": "...",
        "source": "...",
        "url": "...",
        "image": "...",
        "date": "..."
      }
    ],
    "filter": "wildfire",
    "fetched_at": "..."
  }
}
```

### 💻 Dashboard Integration (App 5)
The News Dashboard in `/app5/` reads directly from the `app3` cache files. This decoupling ensures:
- **Instant Loads**: The dashboard never waits for an API call; it serves the latest local cache instantly.
- **Unified Data**: All apps see the same "Truth" from the `Glob_data` directory.
- **API Safety**: No matter how many users open the dashboard, zero extra API calls are made.

---

## Configuration

### API Keys
Ensure your `.env` file contains:
- `NEWS_API_KEY_GLOB`: Your NewsAPI.org key.
- `YOUTUBE_API_KEY`: For the video news feed (integrated into the same sync loop).

### Refresh Intervals
- **Cache Window**: 6 Hours (controlled by `CACHE_HOURS` in `app3/routes.py`).
- **Sync Check**: 30 Minutes (controlled by `background_data_sync_task` in `run.py`).
- **News Throttling**: 7 Seconds (controlled by `NEWS_FETCH_DELAY` in `app3/routes.py`).

## Troubleshooting

### Data is Stale?
- Check the console logs. Look for: `[Background Sync] Checking all data sources...`
- If you see `Events cache is fresh (within 6h) – skipping fetch`, the system is intentionally waiting to conserve API quota.
- To force a refresh, you can delete the `.json` files in `Main/app3/Glob_data/`.

### No News Appearing?
- Verify `NEWS_API_KEY_GLOB` is valid.
- Check `FETCH_ENABLED` in `app3/routes.py`. It must be set to `True` for live fetching.

---
**Status**: ✅ Architecture Modernized  
**Last Updated**: 2026-04-26
