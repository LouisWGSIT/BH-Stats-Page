# QA Stats Dashboard - Database Schema & Integration Guide

## Database Connection
- **Host**: 77.68.90.229
- **Port**: 3306
- **Database**: Billingservices
- **Username**: louiswhitehouse
- **Password**: Gr33nsafeIT2026 (read-only access)

## Key Tables for QA Dashboard

### 1. ITAD_QA_App (Primary QA Data)
**Purpose**: Stores QA scanning records with photos, screenshots, and timestamps

**Columns**:
- `id` (int) - Primary key
- `added_date` (datetime) - When QA scan was added
- `stockid` (varchar) - Asset/device stock ID
- `scanned_response` (longtext) - QA scanning results/data
- `photo_location` (longtext) - Path to webcam photo
- `screenshot_location` (longtext) - Path to screenshot
- `log_file_location` (longtext) - Path to logs
- `QA_instruction` (longtext) - QA instructions/notes
- `updated_date` (datetime) - Last update timestamp
- `username` (varchar) - QA technician email (9 unique users)
- `scanned_location` (varchar) - Physical location (IA Roller 1-7)
- `location` (varchar) - Currently NULL, reserved for future use

**Data Range**: Nov 7, 2024 - Mar 17, 2025 (24,648 records)

**QA Technicians** (9 total):
- matt.payton@greensafeit.com
- georgina.bartley@greensafeit.com
- tom.archer@greensafeit.com
- mark.aldington@greensafeit.com
- connor.mills@greensafeit.com
- jason.arrow@greensafeit.com
- brandon.brace@greensafeit.com
- Alessandro.Aloisi@greensafeit.com
- NO USER (unassigned entries)

**Physical Locations** (7 Rollers):
- IA Roller 1-7

### 2. ITAD_asset_info_blancco (Device + Erasure Details)
**Purpose**: Stores device specifications and erasure completion status

**Key Columns**:
- `id` (int) - Primary key
- `stockid` (varchar) - Links to device
- `manufacturer` (varchar) - Device brand
- `model` (varchar) - Device model
- `serial` (varchar) - Device serial number
- `chassis_type` (varchar) - Device type (Mobile Device, Laptop, etc.)
- `disks` (text) - JSON/serialized disk information (serial, capacity, vendor)
- `erasures` (text) - JSON/serialized erasure records with:
  - `erasure_completed` (datetime)
  - `elapsed_time` (duration)
  - `erasure_type` (method used)
  - `erasure_status` ("Successful", "Failed", etc.)
- `storage_type` (varchar)
- `storage_size` (varchar)

### 3. ITAD_asset_info (Complete Asset Information)
**Purpose**: Master asset table with 338,855+ records

**Key Columns** (first 20):
- `sysid` (int) - Primary key
- `stockid` (varchar) - Asset identifier
- `source` (varchar) - Data source
- `order_type` (varchar) - Type of order
- `manufacturer` (varchar) - Brand
- `description` (varchar)
- `category` (varchar)
- `warehouse` (varchar) - Storage location
- `condition` (varchar) - Current condition grade
- `received_date` (date)
- `initial_grade` (varchar)
- `de_complete` (varchar) - Data Erasure complete flag
- `de_status` (varchar) - Data Erasure status
- ... (124 more columns for testing, grading, pricing, etc.)

### 4. ITAD_QA_override (User Management)
**Purpose**: Maps override codes to QA technician names

**Columns**:
- `id` (int)
- `override_code` (varchar) - User-specific code
- `User` (varchar) - Full name

## Dashboard Metrics to Implement

### Sheet 1: QA Daily Summary
**Columns**:
- Date
- QA Technician (from `username`)
- Devices Scanned (COUNT from ITAD_QA_App)
- Pass Rate (%) - Based on scanned_response success indicators
- Location (IA Roller 1-7)
- Avg Time per Device
- Photos Captured (COUNT non-null photo_location)

### Sheet 2: QA by Technician (This Week)
**Columns**:
- Technician Name
- Total Scanned (This Week)
- Pass Rate (This Week %)
- Avg/Day
- Mon | Tue | Wed | Thu | Fri counts
- Comparison vs Last Week (delta)

### Sheet 3: QA by Location
**Columns**:
- Location (IA Roller)
- Devices Scanned (This Week)
- Pass Rate (%)
- Top Technician
- Avg Time per Device

### Sheet 4: Device Quality Trends
**Columns**:
- Device Model
- Units Scanned (This Week)
- Pass Rate (%)
- Common Issues (from QA_instruction)
- Manufacturer (from ITAD_asset_info_blancco)

### Sheet 5: Technician Performance KPIs
**Columns**:
- Technician
- Total Units Processed
- Consistency Score (0-100 based on daily variance)
- Pass Rate (%)
- Avg Scan Time
- Defect Detection Rate
- Reliability Score (0-100)

## Implementation Notes

### Data Relationship
```
ITAD_QA_App.stockid ← → ITAD_asset_info_blancco.stockid
ITAD_QA_App.stockid ← → ITAD_asset_info.stockid
```

### Pass/Fail Determination
Since `scanned_response` field is not fully documented, we need to:
1. **Option A**: Examine a few actual `scanned_response` values to understand the format
2. **Option B**: Use presence of data in fields as proxy:
   - `photo_location` present = "Pass" (device captured successfully)
   - `QA_instruction` with content = "Fail" or "Review needed"
   - Consider date - if `updated_date` is significantly after `added_date` = "Re-scanned"

### Time-Based Filtering
- Use `added_date` for daily/weekly reports
- Support same reporting periods as Erasure Stats:
  - This Week (Monday-Friday of current week)
  - Last Week (Monday-Friday of previous week)
  - This Month
  - Last Month

### Performance Optimization
- Pre-aggregate data for past dates (don't recalculate weekly)
- Cache technician performance scores
- Consider creating views for common queries

## Next Steps

1. **Examine scanned_response format** - Pull a few actual values to understand pass/fail indicators
2. **Parse QA_instruction field** - Extract common rejection reasons for dashboard
3. **Build qaStats export module** - Mirror engineer_export.py structure
4. **Create MariaDB connection pool** - For persistent connection with retry logic
5. **Add QA sheet to Excel export** - Integrate into existing export flow
6. **Update dashboard HTML** - Add QA Stats view with period selection
