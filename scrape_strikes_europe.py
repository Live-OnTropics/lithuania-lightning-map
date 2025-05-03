## scrape_strikes_europe.py
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
DATA_FILE = "strikes_europe.json" # <--- Correct output filename for Europe

# Bounding box for filtering *in the Python script*.
# Set to None if you want to process ALL strikes scraped from the website's default view (likely covering Europe).
# Set to a BBOX if you want to filter to a smaller region AFTER scraping.
# FILTER_BBOX = None <--- Correct setting for covering Europe using the map's default view

# Example BBOX for Lithuania if you ever wanted to filter again:
FILTER_BBOX = {"min_lat": 30, "max_lat": 75, "min_lon": -30, "max_lon": 45}

# Keep data for the last X hours in the JSON file (provides buffer for map)
HOURS_TO_KEEP_IN_JSON = 3 # Keep 6 hours of data in the file (map displays last 1 hour)

SCRAPE_URL = "https://map.blitzortung.org/" # The website to scrape

# --- Helper Functions (Identical) ---
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
        return None

# --- Scraping Function (Identical - scrapes whatever the map shows) ---
def scrape_blitzortung_strikes():
    """
    Uses Selenium with Microsoft Edge in headless mode to visit
    map.blitzortung.org and scrape the raw strike data objects
    that the website loads into its JavaScript environment.
    """
    print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Initializing Edge WebDriver...")
    options = EdgeOptions()
    options.use_chromium = True
    options.add_argument("--headless") # Run browser without a GUI
    options.add_argument("--no-sandbox") # Recommended for headless environments to prevent crashes
    options.add_argument("--disable-dev-shm-usage") # Addresses limited resource issues in some environments
    options.add_argument("--log-level=3") # Suppress verbose browser logging
    # Set a user agent to appear more like a standard browser
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36 Edg/90.0.818.49")

    driver = None # Initialize driver variable
    try:
        # Use webdriver-manager to automatically download and configure the Edge driver
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=options)
        driver.set_page_load_timeout(30) # Set a timeout for page navigation

        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Navigating to {SCRAPE_URL}...")
        driver.get(SCRAPE_URL)

        # Wait for the map and lightning data to load via JavaScript.
        # This time might need adjustment based on your internet speed and the website's loading time.
        wait_time = 1 # Seconds
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Waiting {wait_time}s for data load...")
        time.sleep(wait_time)

        # --- JavaScript to Extract Strike Data ---
        # This script is executed *within* the headless browser context.
        # It attempts to find the strike data array which is often stored
        # in global variables (like `window.Strikes`) or within map library sources (like Mapbox GL JS).
        # This part is fragile if the website's internal structure changes.
        script = """
            var rawStrikes = []; // Initialize an empty array to store results
            try {
                // Attempt 1: Check for a global variable named 'Strikes'
                if (typeof window.Strikes !== 'undefined' && Array.isArray(window.Strikes)) {
                    rawStrikes = window.Strikes;
                }
                // Attempt 2: If using Mapbox GL JS, check GeoJSON data sources attached to the 'map' object
                else if (typeof map !== 'undefined' && typeof map.getStyle === 'function') {
                    var sources = map.getStyle().sources; // Get all data sources defined on the map
                    for (var key in sources) { // Loop through sources
                        // Check if source is GeoJSON, has data, and data has features (GeoJSON standard)
                        if (sources[key].type === 'geojson' && sources[key].data && Array.isArray(sources[key].data.features)) {
                           rawStrikes = sources[key].data.features; // Found the data, take the features array
                           break; // Stop searching once a likely source is found
                        }
                    }
                }
                // Add more checks here if you find other places the data might be stored (using DevTools)

            } catch (e) {
                // Log any errors that occur during the JavaScript execution itself
                console.error('JS Error executing script to find strikes:', e);
            }
            // Return the found data (or empty array if nothing was found) as a JSON string
            return JSON.stringify(rawStrikes);
        """
        # print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Executing script...") # Verbose
        strikes_data_json = driver.execute_script(script)
        # Parse the JSON string returned by the script back into a Python list/dict
        scraped_strikes = json.loads(strikes_data_json) if strikes_data_json else []
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Scraped {len(scraped_strikes)} raw objects from browser.")
        # Debug: Uncomment to print the first raw object to inspect its structure
        # if scraped_strikes:
        #    print("First raw scraped object sample:")
        #    pprint.pprint(scraped_strikes[0])


    except Exception as e:
        # Catch any errors during WebDriver initialization or page loading/script execution
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] WebDriver/Script execution error: {e}")
        scraped_strikes = [] # Ensure an empty list is returned on error
    finally:
        # Always quit the driver to clean up browser processes
        if driver:
            # print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Quitting WebDriver.") # Verbose
            driver.quit()

    return scraped_strikes

# --- Main Data Update Logic ---
def run_scrape_and_update():
    """
    Main function to run one cycle: load existing data, scrape new,
    process/filter, merge, filter by time, and save.
    """
    start_run_time = get_utc_now()
    # Use DATA_FILE in the log message for clarity
    print(f"[{start_run_time.strftime('%Y-%m-%d %H:%M:%S Z')}] Starting scrape cycle (Saving to {DATA_FILE})...")

    # 1. Load existing data from the specified DATA_FILE
    all_strikes_list = [] # Initialize an empty list
    # Check if the DATA_FILE exists
    if os.path.exists(DATA_FILE): # <--- Correctly using DATA_FILE
        try:
            # Open and load JSON from the DATA_FILE
            with open(DATA_FILE, "r", encoding='utf-8') as f: # <--- Correctly using DATA_FILE
                all_strikes_list = json.load(f)
                # Ensure the loaded data is actually a list
                if not isinstance(all_strikes_list, list):
                    print(f"Warning: Data file {DATA_FILE} does not contain a list at the root. Starting fresh.") # <--- Use DATA_FILE
                    all_strikes_list = [] # Reset if format is wrong
        except (json.JSONDecodeError, IOError) as e:
            # Handle file reading or JSON parsing errors
            print(f"Warning: Error loading {DATA_FILE}, starting fresh: {e}") # <--- Correctly using DATA_FILE in message
            all_strikes_list = [] # Start fresh on error

    # Create a set of existing strike identifiers for fast duplicate checking
    # The key for the set is a tuple: (timestamp_string, latitude_float, longitude_float)
    existing_strike_ids = set((s['time'], s['lat'], s['lon']) for s in all_strikes_list if 'time' in s and 'lat' in s and 'lon' in s) # Add checks for safety
    initial_count = len(all_strikes_list)
    print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Loaded {initial_count} existing strikes from {DATA_FILE}") # <--- Correctly using DATA_FILE in message

    # 2. Scrape new strikes using the defined scraping function
    new_raw_strikes = scrape_blitzortung_strikes()

    # 3. Process, Validate, Filter (if BBOX is set), and Format new strikes
    added_count = 0
    skipped_malformed = 0 # Counter for strikes that don't match the expected structure
    skipped_bbox = 0 # Counter for strikes outside the BBOX (if filter is active)
    
    if not new_raw_strikes:
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] No new raw objects were scraped. Nothing to process.")
    else:
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Processing {len(new_raw_strikes)} scraped raw objects...")
        for raw_strike in new_raw_strikes:
            # Ensure raw_strike is a dictionary before attempting to access keys
            if not isinstance(raw_strike, dict):
                skipped_malformed += 1
                continue # Skip non-dictionary items

            try:
                # Extract coordinates - expecting GeoJSON Feature structure { "geometry": { "coordinates": [lon, lat] } }
                coords = raw_strike.get('geometry', {}).get('coordinates') # Use .get() for safe access
                if not isinstance(coords, list) or len(coords) < 2:
                     skipped_malformed += 1; continue # Skip if coordinates not found or not a list of 2

                # Convert coordinates to floats
                lon = float(coords[0])
                lat = float(coords[1])

                # --- Timestamp Extraction (CRITICAL - VERIFY THIS BASED ON ACTUAL DATA) ---
                # Blitzortung often uses nanosecond Unix timestamps stored somewhere,
                # commonly in the 'properties' dictionary within the GeoJSON Feature.
                # Example: Look for a 'time' key within 'properties'.
                timestamp_ns = raw_strike.get('properties', {}).get('time')

                strike_time_str = None # Initialize formatted timestamp string
                if timestamp_ns is not None: # Check if we found a potential timestamp
                    try:
                         # Assuming the timestamp found is in nanoseconds.
                         # If your actual scraped data is in milliseconds, change 1_000_000_000.0 to 1000.0
                         ts_seconds = float(timestamp_ns) / 1_000_000_000.0
                         # Convert Unix timestamp (seconds) to a timezone-aware datetime object (UTC)
                         strike_dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
                         # Format the datetime object into the desired ISO 8601 string format
                         strike_time_str = format_timestamp(strike_dt)
                    except (ValueError, TypeError):
                         # Handle errors during timestamp conversion (e.g., if timestamp_ns wasn't a valid number)
                         # print(f"Warning: Could not convert suspected timestamp '{timestamp_ns}'. Using current time as fallback.") # Debug warning
                         strike_time_str = format_timestamp(get_utc_now()) # Fallback: Use current time (less accurate)
                else:
                     # Handle cases where the timestamp property wasn't found at all
                     # print("Warning: No timestamp property found in raw object. Using current time as fallback.") # Debug warning
                     # pprint.pprint(raw_strike) # Debug: Uncomment to see the raw object that failed
                     strike_time_str = format_timestamp(get_utc_now()) # Fallback

                # --- End Timestamp Extraction ---

                # Apply BBOX filter (only if FILTER_BBOX is explicitly set to a dictionary)
                # This check ensures we only filter geographically if FILTER_BBOX is NOT None.
                if FILTER_BBOX: # <--- This condition correctly checks if filtering is enabled
                    if not (FILTER_BBOX["min_lat"] <= lat <= FILTER_BBOX["max_lat"] and
                            FILTER_BBOX["min_lon"] <= lon <= FILTER_BBOX["max_lon"]):
                        skipped_bbox += 1; continue # Skip this strike if outside the BBOX

                # Format the strike data into the standard dictionary structure for our JSON file
                strike_data = {
                    "lat": lat,
                    "lon": lon,
                    "time": strike_time_str # Use the formatted timestamp string
                }

                # Check for duplicates using the identifier derived from the formatted data
                strike_id = (strike_data['time'], strike_data['lat'], strike_data['lon'])
                if strike_id not in existing_strike_ids:
                    all_strikes_list.append(strike_data) # Add the new unique strike to our list
                    existing_strike_ids.add(strike_id) # Add its ID to the set to prevent future duplicates in this run
                    added_count += 1 # Increment the counter for added strikes
                # else: This strike is a duplicate, so we do nothing and it's skipped.

            except (KeyError, TypeError, ValueError, IndexError) as e:
                 # Catch errors related to accessing expected keys or converting types
                 # print(f"Warning: Skipping malformed/unexpected raw object structure ({e}).") # Debug warning
                 # pprint.pprint(raw_strike) # Debug: Uncomment to see the problematic raw object
                 skipped_malformed += 1 # Increment counter for malformed strikes

        # Print summary of processing results
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Processing Summary:")
        # Only print BBOX summary if filtering was active and some strikes were skipped
        if FILTER_BBOX and skipped_bbox > 0: print(f"  - Skipped {skipped_bbox} strikes outside BBOX.")
        # Always print malformed summary if any were skipped
        if skipped_malformed > 0: print(f"  - Skipped {skipped_malformed} malformed raw objects.")
        # Always print added summary
        print(f"  - Added {added_count} new unique strikes.")


    # 4. Filter the combined list (existing + newly added) to keep only strikes
    # within the last HOURS_TO_KEEP_IN_JSON hours.
    cutoff_time = get_utc_now() - timedelta(hours=HOURS_TO_KEEP_IN_JSON)
    original_total = len(all_strikes_list)
    # Use a list comprehension to build the new filtered list
    filtered_strikes = [
        s for s in all_strikes_list
        # Attempt to parse the timestamp string; filter if parsing fails or if the strike is older than cutoff
        if (dt := parse_iso_timestamp(s.get("time", ""))) is not None and dt >= cutoff_time
    ]
    removed_old_count = original_total - len(filtered_strikes) # Calculate how many were removed

    if removed_old_count > 0:
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Removed {removed_old_count} strikes older than {HOURS_TO_KEEP_IN_JSON}h.")

    # 5. Save the final filtered list to the specified DATA_FILE
    final_count = len(filtered_strikes) # The number of strikes remaining after filtering
    try:
        # Use a temporary file for atomic saving
        temp_file = DATA_FILE + ".tmp" # <--- Correctly using DATA_FILE
        # Open the temporary file for writing
        with open(temp_file, "w", encoding='utf-8') as f:
            # Dump the filtered list as the root JSON object with indentation (2 spaces)
            json.dump(filtered_strikes, f, indent=2, ensure_ascii=False)
        # Replace the old DATA_FILE with the new temporary file
        os.replace(temp_file, DATA_FILE) # <--- Correctly using DATA_FILE
        # Print success message
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Successfully saved {final_count} strikes to {DATA_FILE}") # <--- Correctly using DATA_FILE in message
    except Exception as e:
        # Handle errors during file writing or replacement
        print(f"[{get_utc_now().strftime('%Y-%m-%d %H:%M:%S Z')}] Error saving data to {DATA_FILE}: {e}") # <--- Correctly using DATA_FILE in message
        # Attempt to clean up the temporary file if an error occurred after creating it
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except OSError: pass # Ignore errors during cleanup

    # End of the scrape cycle
    end_run_time = get_utc_now()
    duration = end_run_time - start_run_time
    print(f"[{end_run_time.strftime('%Y-%m-%d %H:%M:%S Z')}] Scrape cycle finished in {duration.total_seconds():.2f}s.")

# This block allows you to run the script directly for a single update
if __name__ == "__main__":
    run_scrape_and_update()