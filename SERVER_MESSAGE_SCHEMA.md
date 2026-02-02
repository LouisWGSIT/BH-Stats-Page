# Server Message Schema

## Automatic Device Details Capture

The dashboard automatically captures device details from Blancco in two ways:

1. **From Webhook Payload**: Extracts hardware details if Blancco includes them in the webhook
2. **From Blancco API**: Falls back to querying Blancco API using the jobId if details aren't in payload

**No manual configuration needed!** The system will automatically try multiple field names that Blancco commonly uses.

## Webhook Payload Format

Send POST requests to `/hooks/erasure-detail` with the following JSON payload:

```json
{
  "event": "success",
  "jobId": "<DEVICECUSTOMFIELD AssetTag>",
  "deviceType": "laptops_desktops|servers|macs|mobiles",
  "initials": "<DEVICECUSTOMFIELD Engineer Initials>",
  "durationSec": 0,
  "timestamp": "",
  "deviceDetails": {
    "manufacturer": "HP|Dell|Apple|Lenovo|etc",
    "model": "EliteBook 840 G5|ProDesk 600 G4|MacBook Pro|etc",
    "driveSize": 512,
    "driveCount": 1,
    "driveType": "HDD|SSD|NVMe"
  }
}
```

### Automatic Field Detection

The system automatically checks for device details using these field names (case-insensitive):

**Manufacturer:**
- `manufacturer`, `Manufacturer`, `hardwareManufacturer`

**Model:**
- `model`, `Model`, `chassisType`, `ChassisType`

**Drive Size (in GB):**
- `driveSize`, `totalDriveCapacity`, `storageCapacity`

**Drive Count:**
- `driveCount`, `numberOfDrives`

**Drive Type:**
- `driveType`, `storageType`, `mediaType` (HDD, SSD, NVMe)

If Blancco's webhook already includes any of these fields, they'll be captured automatically!

### Blancco API Integration (Optional)

If device details aren't in the webhook payload, the system can query Blancco's API:

Set these environment variables on Render:
```
BLANCCO_API_URL=https://your-blancco-api-url.com
BLANCCO_API_KEY=your-api-key-here
```

The system will automatically fetch device details using the jobId.

### Field Descriptions

#### Required Fields:
- **event**: `"success"` or `"failure"` - Status of the erasure
- **jobId**: Unique identifier for the job (Asset Tag from device)
- **deviceType**: Category of device being erased
  - `laptops_desktops` - Laptops and desktop computers
  - `servers` - Server equipment
  - `macs` - Apple Mac computers
  - `mobiles` - Mobile phones and tablets

#### Optional Fields:
- **initials**: Engineer's initials performing the erasure (2-4 characters)
- **durationSec**: Time taken to complete erasure in seconds
- **timestamp**: ISO 8601 timestamp of when erasure completed

#### Device Details (Optional but Recommended):
The `deviceDetails` object helps explain performance differences between engineers:

- **manufacturer**: Device manufacturer name (e.g., "HP", "Dell", "Apple")
- **model**: Specific model identifier (e.g., "EliteBook 840 G5", "ProDesk 600")
- **driveSize**: Total drive capacity in GB (integer)
- **driveCount**: Number of drives in the device (integer)
- **driveType**: Type of storage drive
  - `HDD` - Hard Disk Drive (slower, traditional)
  - `SSD` - Solid State Drive (faster)
  - `NVMe` - NVMe SSD (fastest)

### Why Device Details Matter

Device details help contextualize engineer performance:
- **Larger drives take longer**: 2TB drive vs 256GB SSD
- **Multiple drives take longer**: Server with 4 drives vs laptop with 1
- **Drive type affects speed**: HDD erasure takes longer than SSD
- **Older devices may be slower**: Different hardware generations

This data ensures fair performance comparisons and helps identify which engineers handle more complex jobs.

### Example Messages

#### Simple Laptop Erasure:
```json
{
  "event": "success",
  "jobId": "PC123456",
  "deviceType": "laptops_desktops",
  "initials": "MS",
  "durationSec": 1800,
  "timestamp": "2026-02-02T14:30:00Z",
  "deviceDetails": {
    "manufacturer": "HP",
    "model": "EliteBook 840 G5",
    "driveSize": 256,
    "driveCount": 1,
    "driveType": "SSD"
  }
}
```

#### Complex Server Erasure:
```json
{
  "event": "success",
  "jobId": "SRV789012",
  "deviceType": "servers",
  "initials": "JD",
  "durationSec": 7200,
  "timestamp": "2026-02-02T16:45:00Z",
  "deviceDetails": {
    "manufacturer": "Dell",
    "model": "PowerEdge R740",
    "driveSize": 8000,
    "driveCount": 4,
    "driveType": "HDD"
  }
}
```

### Migration Notes

- Existing server messages without `deviceDetails` will continue to work
- Database schema automatically migrates to add new columns
- Old records will have NULL values for device details
- New analytics will show "Unknown" for devices without details

### Authentication

Include API key in request headers:
```
Authorization: Bearer YOUR_API_KEY
```
or
```
x-api-key: YOUR_API_KEY
```
