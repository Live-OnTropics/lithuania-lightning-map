# scrape_strikes.py
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from webdriver_manager.microsoft import EdgeChromiumDriverManager
import time
import json
from datetime import datetime, timedelta, timezone
import os
import pprint # For debugging if needed

# --- Configuration ---
DATA_FILE = "strikes.json"
# Lithuania Bounding Box
FILTER_BBOX = {"min_lat": 53.9, "max_lat": 56.5, "min_lon": 20.9, "max_lon": 26.8}
# FILTER_BBOX = None # Uncomment to disable geographic filtering

# Keep data for the last X hours in the JSON file (provides buffer for map)
HOURS_TO_KEEP_IN_JSON = 6 

SCRAPE_URL = "https://map.blitzortung.org/"

# --- Helper Functions ---
def get_utc_now():
    return datetime.now(timezone.utc)

def format_timestamp(dt_object):
    if dt_object.tzinfo is None:
        dt_object = dt_object.replace(tzinfo=timezone.utc)
    return dt_object.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def parse_iso_timestamp(ts_string):
    try:
        if ts_string.endswith('Z'):
            ts_string = ts_string[:-1] + '+00:00'
        dt = datetime.fromisoformat(ts_string)
        if dt.tzinfo is None:
             dt = dt.replace(tzinfo=timezone.utc)
        elif dt.tzinfo != timezone.utc:
             dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        # print(f"Warning: Could not parse timestamp: {ts_string}") # Optional warning
        return None

# --- Scraping Function ---
def scrape_blitzortung_strikes():
    print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Initializing Edge WebDriver...")
    options = EdgeOptions()
    options.use_chromium = True
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36 Edg/90.0.818.49")

    driver = None
    try:
        # print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Setting up msedgedriver...") # Verbose
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=options)
        driver.set_page_load_timeout(45)

        # print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Navigating to {SCRAPE_URL}...") # Verbose
        driver.get(SCRAPE_URL)

        wait_time = 40
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Waiting {wait_time}s for data load...")
        time.sleep(wait_time)

        script = """
            var rawStrikes = [];
            try {
                if (typeof window.Strikes !== 'undefined' && Array.isArray(window.Strikes)) { rawStrikes = window.Strikes; }
                else if (typeof map !== 'undefined' && typeof map.getStyle === 'function') {
                    var sources = map.getStyle().sources;
                    for (var key in sources) {
                        if (sources[key].type === 'geojson' && sources[key].data && Array.isArray(sources[key].data.features)) {
                           rawStrikes = sources[key].data.features; break;
                        } } }
            } catch (e) { console.error('JS Error:', e); }
            return JSON.stringify(rawStrikes);
        """
        # print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Executing script...") # Verbose
        strikes_data_json = driver.execute_script(script)
        scraped_strikes = json.loads(strikes_data_json) if strikes_data_json else []
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Scraped {len(scraped_strikes)} raw objects.")
        # if scraped_strikes: pprint.pprint(scraped_strikes[0]) # Debug: Print first object

    except Exception as e:
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] WebDriver/Script error: {e}")
        scraped_strikes = []
    finally:
        if driver:
            # print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Quitting WebDriver.") # Verbose
            driver.quit()
    return scraped_strikes

# --- Main Data Update Logic ---
def run_scrape_and_update():
    """Loads existing data, scrapes new data, filters, merges, and saves."""
    start_run_time = get_utc_now()
    print(f"[{start_run_time.strftime('%Y-%m-%d %H:%M:%S Z')}] Starting scrape cycle...")

    # 1. Load existing
    all_strikes_list = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding='utf-8') as f:
                all_strikes_list = json.load(f)
                if not isinstance(all_strikes_list, list): all_strikes_list = []
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Error loading {DATA_FILE}, starting fresh: {e}")
            all_strikes_list = []
    
    existing_strike_ids = set((s['time'], s['lat'], s['lon']) for s in all_strikes_list)
    initial_count = len(all_strikes_list)

    # 2. Scrape new
    new_raw_strikes = scrape_blitzortung_strikes()

    # 3. Process & Filter new
    added_count = 0
    skipped_malformed = 0
    skipped_bbox = 0
    
    if new_raw_strikes:
        for raw_strike in new_raw_strikes:
            try:
                # --- Adapt parsing based on actual data structure ---
                coords = raw_strike.get('geometry', {}).get('coordinates')
                if not isinstance(coords, list) or len(coords) < 2:
                     skipped_malformed += 1; continue
                lon, lat = float(coords[0]), float(coords[1])

                # --- Timestamp (CRITICAL - VERIFY THIS) ---
                # Assuming nanoseconds in properties.time
                timestamp_ns = raw_strike.get('properties', {}).get('time') 
                if timestamp_ns:
                    try:
                         ts_seconds = float(timestamp_ns) / 1_000_000_000.0
                         strike_dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
                         strike_time_str = format_timestamp(strike_dt)
                    except (ValueError, TypeError): 
                         strike_time_str = format_timestamp(get_utc_now()) # Fallback
                         # print(f"Warn: Bad TS {timestamp_ns}") # Debug
                else:
                     strike_time_str = format_timestamp(get_utc_now()) # Fallback
                # --- End Timestamp ---

                if FILTER_BBOX:
                    if not (FILTER_BBOX["min_lat"] <= lat <= FILTER_BBOX["max_lat"] and
                            FILTER_BBOX["min_lon"] <= lon <= FILTER_BBOX["max_lon"]):
                        skipped_bbox += 1; continue

                strike_data = {"lat": lat, "lon": lon, "time": strike_time_str}
                strike_id = (strike_data['time'], strike_data['lat'], strike_data['lon'])

                if strike_id not in existing_strike_ids:
                    all_strikes_list.append(strike_data)
                    existing_strike_ids.add(strike_id)
                    added_count += 1
                # else: duplicate, ignore

            except (KeyError, TypeError, ValueError, IndexError) as e:
                 # print(f"Warn: Skipping malformed: {e}") # Debug
                 # pprint.pprint(raw_strike) # Debug
                 skipped_malformed += 1
        
        # Print summary of processing
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Processing Summary:")
        if skipped_bbox > 0: print(f"  - Skipped {skipped_bbox} outside BBOX.")
        if skipped_malformed > 0: print(f"  - Skipped {skipped_malformed} malformed.")
        print(f"  - Added {added_count} new unique strikes.")


    # 4. Filter overall list by time window (e.g., keep last 6 hours)
    cutoff_time = get_utc_now() - timedelta(hours=HOURS_TO_KEEP_IN_JSON)
    original_total = len(all_strikes_list)
    filtered_strikes = [
        s for s in all_strikes_list
        if (dt := parse_iso_timestamp(s.get("time", ""))) is not None and dt >= cutoff_time
    ]
    removed_old_count = original_total - len(filtered_strikes)

    if removed_old_count > 0:
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Removed {removed_old_count} strikes older than {HOURS_TO_KEEP_IN_JSON}h.")

    # 5. Save updated list
    final_count = len(filtered_strikes)
    try:
        # Create temporary file path
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding='utf-8') as f:
            json.dump(filtered_strikes, f, indent=2, ensure_ascii=False) # Use indent=2 for smaller file size
        # Atomically replace the old file with the new one
        os.replace(temp_file, DATA_FILE)
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Saved {final_count} strikes to {DATA_FILE}")
    except Exception as e:
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Error saving {DATA_FILE}: {e}")
        # Attempt to remove temporary file if it exists
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass

    end_run_time = get_utc_now()
    duration = end_run_time - start_run_time
    print(f"[{end_run_time.strftime('%Y-%m-%d %H:%M:%S Z')}] Scrape cycle finished in {duration.total_seconds():.2f}s.")

# Allow running this script directly for a single update if needed
if __name__ == "__main__":
    run_scrape_and_update()