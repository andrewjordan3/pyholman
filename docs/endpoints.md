# Endpoints

Holman's Customer Data API exposes per-vehicle records across several domains: vehicle master data, maintenance work orders, contact / driver assignments, and the two telemetry-style readings (odometer and engine hours). pyholman currently supports five of those endpoints, each modeled as a Pydantic class under `src/pyholman/_endpoints/<name>/response.py`. This document is the conceptual reference for what each one returns and accepts; for the operational filter syntax (YAML keys, defaults, etc.) see `user_config.example.yaml`.

More endpoints may be added in the future as additional Holman query endpoints are integrated. Until then, the five sections below are exhaustive.

## vehicles

Per-vehicle master record. One row per vehicle in the lessee's fleet, covering identification, lease, telematics, location, and assignment. Incremental-capable; the watermark column is `last_change_date`.

### Request

- **URL path:** `/CustomerDataAPI/vehicles/basic-query`
- **Required parameters:** `lessee_codes` (provided by `UserConfig.fleet`); `paging` (handled by pyholman).
- **Optional filters:**
  - `last_change_date` — tz-aware UTC cursor for delta queries; pyholman stamps this from the prior run's watermark on incremental refreshes.
  - `status_codes` — tuple of Holman statusCodes to include. Valid values: `0` (ordered), `1` (active), `2` (out-of-service), `3` (sold). Any other value is rejected at config load.
  - `sold_date_code` — derived automatically from `status_codes`; not user-configurable. When `status_codes` includes `3`, pyholman emits `5` ("all sold assets regardless of sale date").
- **Refresh mode:** incremental.

### Response fields

| Wire name | Python attribute | Type | Description | Notes |
|---|---|---|---|---|
| `addressLine1` | `address_line_1` | `str \| None` | Driver mailing address line 1 | — |
| `addressLine2` | `address_line_2` | `str \| None` | Driver mailing address line 2 | — |
| `addressLine3` | `address_line_3` | `str \| None` | Driver mailing address line 3 | — |
| `assetSubtype` | `asset_subtype` | `str \| None` | Secondary vehicle classification dependent on `asset_type`; see Holman's Asset Type and Asset Sub-Type reference list | — |
| `assetType` | `asset_type` | `str \| None` | Asset category — e.g., `"TRAILER"`, `"CAR"` | — |
| `assignedStatus` | `assigned_status` | `str \| None` | Additional optional classification of how the vehicle is currently being used; see Holman's Assigned Status reference list | — |
| `auxData1`–`auxData14` | `aux_data_1`–`aux_data_14` | `str \| None` | Holman-defined auxiliary data fields | Free-text per tenant |
| `auxDate1`–`auxDate4` | `aux_date_1`–`aux_date_4` | `datetime \| None` | Holman-defined auxiliary date fields | — |
| `capCost` | `cap_cost` | `float \| None` | Capitalized cost at lease inception | Coerced from quoted-numeric wire string |
| `cellPhone` | `cell_phone` | `str \| None` | Driver cell phone | — |
| `city` | `city` | `str \| None` | Driver mailing city | — |
| `clientData1`–`clientData7` | `client_data_1`–`client_data_7` | `str \| None` | Client-defined custom fields | Free-text per tenant |
| `clientVehicleNumber` | `client_vehicle_number` | `str \| None` | Vehicle number assigned by the client | Identifier; keep as string |
| `curbWeight` | `curb_weight` | `int \| None` | Curb weight in pounds | Coerced from zero-padded wire string; `"000000"` → `0` |
| `deliveryDate` | `delivery_date` | `datetime \| None` | Date the vehicle was delivered to the client | — |
| `division` | `division` | `str \| None` | Holman division code — e.g., `"05"`, `"WR"` | Code; leading zeros and alpha values are meaningful |
| `driveline` | `driveline` | `str \| None` | Driveline configuration — e.g., `"FWD"` | — |
| `driverClass` | `driver_class` | `str \| None` | Client-defined custom field (single character) | — |
| `email` | `email` | `str \| None` | Driver email address | — |
| `engineType` | `engine_type` | `str \| None` | Engine description — e.g., `"L4, 2.3L"` | — |
| `exec` | `exec_` | `str \| None` | Client-defined custom field (single character) | Trailing underscore avoids the Python `exec` builtin |
| `firstName` | `first_name` | `str \| None` | Driver first name | — |
| `fuelCapacity` | `fuel_capacity` | `float \| None` | Fuel tank capacity in `fuel_measure_type` units | — |
| `fuelMeasureType` | `fuel_measure_type` | `str \| None` | Unit for `fuel_capacity` — e.g., `"G"` (gallons) | — |
| `fuelType` | `fuel_type` | `str \| None` | Fuel type free-text | — |
| `fuelTypeCode` | `fuel_type_code` | `str \| None` | Fuel type code — e.g., `"00"`, `"01"` | Code; leading zeros are meaningful |
| `fuelTypeDescription` | `fuel_type_description` | `str \| None` | Fuel type description — e.g., `"Diesel"` | — |
| `gvwr` | `gvwr` | `int \| None` | Gross vehicle weight rating in pounds | `0` indicates unset |
| `holmanVehicleNumber` | `holman_vehicle_number` | `str \| None` | Holman's internal vehicle identifier | Identifier |
| `homePhone` | `home_phone` | `str \| None` | Driver home phone | — |
| `hourMeter` | `hour_meter` | `int \| None` | Latest engine-hour reading | — |
| `hourMeterDate` | `hour_meter_date` | `datetime \| None` | Date of `hour_meter` reading | — |
| `lastChangeDate` | `last_change_date` | `datetime \| None` | Watermark for incremental refresh | Cursor field |
| `lastChangeRecordId` | `last_change_record_id` | `int \| None` | Holman's monotonic change-id companion to `last_change_date` | — |
| `lastName` | `last_name` | `str \| None` | Driver last name | — |
| `leaseEndDate` | `lease_end_date` | `datetime \| None` | Scheduled lease end | — |
| `leaseStartDate` | `lease_start_date` | `datetime \| None` | Lease start | — |
| `leaseTerm` | `lease_term` | `int \| None` | Lease term in months | Coerced from quoted-numeric wire string |
| `lesseeCode` | `lessee_code` | `str \| None` | 4-character lessee scope identifier | Identifier |
| `licensePlate` | `license_plate` | `str \| None` | License plate | — |
| `makeClient` | `make_client` | `str \| None` | Vehicle make as named by the client | — |
| `makeVin` | `make_vin` | `str \| None` | Vehicle make as decoded from VIN | — |
| `modelClient` | `model_client` | `str \| None` | Vehicle model as named by the client | — |
| `modelVin` | `model_vin` | `str \| None` | Vehicle model as decoded from VIN | — |
| `modelYear` | `model_year` | `int \| None` | Model year — e.g., `2008` | Coerced from quoted-numeric wire string |
| `monthsBilled` | `months_billed` | `int \| None` | Months billed to date | — |
| `monthsInService` | `months_in_service` | `int \| None` | Months in service | — |
| `odometer` | `odometer` | `int \| None` | Latest odometer reading | Coerced from quoted-numeric wire string |
| `odometerDate` | `odometer_date` | `datetime \| None` | Date of `odometer` reading | — |
| `onRoadDate` | `on_road_date` | `datetime \| None` | Date the vehicle entered service | — |
| `orderType` | `order_type` | `str \| None` | Order type code — e.g., `"D"`, `"F"` | Code |
| `outOfServiceDate` | `out_of_service_date` | `datetime \| None` | Date the vehicle was taken out of service | — |
| `plateType` | `plate_type` | `str \| None` | Plate type code — e.g., `"PAS"`, `"TRL"` | Code |
| `prefix` | `prefix` | `str \| None` | Client-defined custom field (4-character) | — |
| `registeredVehicleWeight` | `registered_vehicle_weight` | `int \| None` | Registered vehicle weight in pounds | Coerced from zero-padded wire string; `"000000"` → `0` |
| `remainingBookValue` | `remaining_book_value` | `float \| None` | Remaining book value | — |
| `renewalDate` | `renewal_date` | `datetime \| None` | Plate / registration renewal date | — |
| `saleOdometer` | `sale_odometer` | `int \| None` | Odometer reading at sale | — |
| `series` | `series` | `str \| None` | Vehicle series / trim | — |
| `soldAmount` | `sold_amount` | `float \| None` | Sale price | — |
| `soldDate` | `sold_date` | `datetime \| None` | Date the vehicle was sold | — |
| `stateProvince` | `state_province` | `str \| None` | Driver mailing state / province | — |
| `status` | `status` | `str \| None` | Status free-text — e.g., `"Active"`, `"Sold Previous Year"` | Pairs with `status_code` |
| `statusCode` | `status_code` | `int \| None` | Status code (`0`/`1`/`2`/`3`) | Filter input shape |
| `tagStateProvince` | `tag_state_province` | `str \| None` | State / province on the license plate | — |
| `telematicsDeviceId` | `telematics_device_id` | `str \| None` | Telematics device identifier | — |
| `telematicsDeviceModel` | `telematics_device_model` | `str \| None` | Telematics device model | — |
| `telematicsDeviceVendor` | `telematics_device_vendor` | `str \| None` | Telematics device vendor | — |
| `titleLocationDescription` | `title_location_description` | `str \| None` | Where the title is held — e.g., `"IN-HOUSE"` | — |
| `titleOwnerLessor` | `title_owner_lessor` | `str \| None` | Title owner / lessor name | — |
| `vendor` | `vendor` | `str \| None` | Vehicle owner; `"ARI"` indicates a Holman-leased asset, other values indicate client-owned or other lessor-owned — see Holman's Vendor reference list for the full set | — |
| `vin` | `vin` | `str \| None` | Vehicle Identification Number | Identifier; length and content vary by asset (older equipment, trailers, and non-VIN identifiers may be shorter) |
| `workPhone` | `work_phone` | `str \| None` | Driver work phone | — |
| `workPhoneExtension` | `work_phone_extension` | `str \| None` | Driver work phone extension | — |
| `zipPostalCode` | `zip_postal_code` | `str \| None` | Driver mailing ZIP / postal code | — |

## maintenance_purchase_orders

One row per maintenance purchase-order line. A "purchase order" in Holman's vocabulary is one line on a maintenance invoice; multiple records share a `po_number` and differ by `po_line_number` and `po_details_id`. The model is line-grained because that is the wire shape; downstream code that wants per-PO aggregates can group on `po_number`. Incremental-capable; the watermark column is `last_change_date`.

### Request

- **URL path:** `/CustomerDataAPI/maintenance/purchase-orders/basic-query`
- **Required parameters:** `lessee_codes`; `paging`.
- **Optional filters:**
  - `last_change_date` — tz-aware UTC cursor for delta queries.
- **Refresh mode:** incremental.

### Response fields

| Wire name | Python attribute | Type | Description | Notes |
|---|---|---|---|---|
| `ataCode` | `ata_code` | `str \| None` | ATA repair code | Code |
| `ataDescription` | `ata_description` | `str \| None` | ATA repair description | — |
| `auxData1`–`auxData14` | `aux_data_1`–`aux_data_14` | `str \| None` | Holman-defined auxiliary data fields | Free-text per tenant |
| `auxDate1`–`auxDate4` | `aux_date_1`–`aux_date_4` | `datetime \| None` | Holman-defined auxiliary date fields | — |
| `billPaidDate` | `bill_paid_date` | `datetime \| None` | Date the bill was paid | — |
| `cause` | `cause` | `str \| None` | Free-text cause of the repair | — |
| `clientData1`–`clientData7` | `client_data_1`–`client_data_7` | `str \| None` | Client-defined custom fields | Free-text per tenant |
| `clientVehicleNumber` | `client_vehicle_number` | `str \| None` | Vehicle number assigned by the client | Identifier |
| `complaint` | `complaint` | `str \| None` | Free-text complaint | — |
| `cost` | `cost` | `float \| None` | Line cost | Wire is sometimes int-shaped (`0`), sometimes decimal (`336.09`) |
| `customerPoNumber` | `customer_po_number` | `str \| None` | Customer-assigned PO number | Identifier; can carry alpha characters |
| `division` | `division` | `str \| None` | Holman division code | Code |
| `driverClass` | `driver_class` | `str \| None` | Client-defined custom field (single character) | — |
| `exec` | `exec_` | `str \| None` | Client-defined custom field (single character) | Trailing underscore avoids the Python `exec` builtin |
| `firstName` | `first_name` | `str \| None` | Driver first name | — |
| `holmanVehicleNumber` | `holman_vehicle_number` | `str \| None` | Holman's internal vehicle identifier | Identifier |
| `hourMeter` | `hour_meter` | `int \| None` | Engine-hour reading at repair | — |
| `invoiceDate` | `invoice_date` | `datetime \| None` | Invoice date | — |
| `invoiceNumber` | `invoice_number` | `str \| None` | Invoice number | Identifier; can carry alpha characters |
| `lastChangeDate` | `last_change_date` | `datetime \| None` | Watermark for incremental refresh | Cursor field |
| `lastChangeRecordId` | `last_change_record_id` | `int \| None` | Holman's monotonic change-id companion | — |
| `lastName` | `last_name` | `str \| None` | Driver last name | — |
| `lesseeCode` | `lessee_code` | `str \| None` | 4-character lessee scope identifier | Identifier |
| `odometer` | `odometer` | `int \| None` | Odometer reading at repair | — |
| `poDate` | `po_date` | `datetime \| None` | PO creation date | — |
| `poDetailsId` | `po_details_id` | `int \| None` | Holman's internal PO-line identifier | — |
| `poLineNumber` | `po_line_number` | `int \| None` | Line number within the PO | — |
| `poNumber` | `po_number` | `int \| None` | Holman's internal PO number | — |
| `poTotalLineCost` | `po_total_line_cost` | `float \| None` | Total cost for the PO line | — |
| `prefix` | `prefix` | `str \| None` | Client-defined custom field (4-character) | — |
| `quantity` | `quantity` | `float \| None` | Line quantity | Decimal; labor hours are commonly fractional (`0.5`, `0.25`, `2.84`) |
| `repairDate` | `repair_date` | `datetime \| None` | Date the repair was performed | — |
| `type` | `type_` | `str \| None` | Line type code — e.g., `"O"` | Trailing underscore avoids the Python `type` builtin |
| `vendorAddressLine1` | `vendor_address_line_1` | `str \| None` | Vendor address line 1 | — |
| `vendorAddressLine2` | `vendor_address_line_2` | `str \| None` | Vendor address line 2 | — |
| `vendorCity` | `vendor_city` | `str \| None` | Vendor city | — |
| `vendorId` | `vendor_id` | `str \| None` | Vendor identifier — e.g., `"000000XX"` | Identifier; alphanumeric |
| `vendorName` | `vendor_name` | `str \| None` | Vendor name | — |
| `vendorStateProvince` | `vendor_state_province` | `str \| None` | Vendor state / province | — |
| `vendorType` | `vendor_type` | `str \| None` | Vendor type code | Code |
| `vendorZipPostalCode` | `vendor_zip_postal_code` | `str \| None` | Vendor ZIP / postal code | — |
| `vin` | `vin` | `str \| None` | Vehicle Identification Number | Identifier; length and content vary by asset (older equipment, trailers, and non-VIN identifiers may be shorter) |

### Sample record

Multiple PO lines share `customerPoNumber` and `holmanVehicleNumber`; they differ by `poLineNumber` and `poDetailsId`. The values below are synthetic placeholders that preserve the wire shape — every identifier and ID has been replaced.

```json
{
  "ataCode": "1D001004",
  "ataDescription": "OUT OF NETWORK FEE",
  "billPaidDate": "2025-07-08T00:00:00Z",
  "cause": "NOT SUPPLIED",
  "complaint": "NOT SUPPLIED",
  "cost": 0,
  "customerPoNumber": "0000000",
  "holmanVehicleNumber": "999999",
  "invoiceDate": "2025-07-08T00:00:00Z",
  "invoiceNumber": "INV0000000",
  "lastChangeDate": "2026-01-28T18:06:36Z",
  "lastChangeRecordId": 100000004,
  "lesseeCode": "XXXX",
  "odometer": 173367,
  "poDate": "2025-07-08T00:00:00Z",
  "poDetailsId": 100000001,
  "poLineNumber": 1,
  "poNumber": 100000000,
  "poTotalLineCost": 0,
  "quantity": 1,
  "repairDate": "2025-07-08T00:00:00Z",
  "type": "O",
  "vendorAddressLine1": "REDACTED",
  "vendorCity": "MOUNT LAUREL",
  "vendorId": "000000XX",
  "vendorName": "HISTORY PO ACCOUNT",
  "vendorStateProvince": "NJ",
  "vendorType": "IV",
  "vendorZipPostalCode": "08054",
  "vin": "1XXXXXXXXXXXXXXXX"
}
```

## contacts

Per-vehicle assigned contact (typically the driver). One row per contact-vehicle assignment. Incremental-capable; the watermark column is `last_change_date`.

The contacts model uses a prefix-stripping convention: wire fields that begin with `contact` (e.g., `contactFirstName`, `contactEmail`, `contactData1`–`contactData7`) drop the prefix on the Python attribute (`first_name`, `email`, `data_1`). "Contact" is implicit in the class name. Wire fields without the prefix (e.g., `city`, `stateProvince`) keep their natural snake_case names. Pydantic aliases preserve the literal Holman wire names.

### Request

- **URL path:** `/CustomerDataAPI/contacts/basic-query`
- **Required parameters:** `lessee_codes`; `paging`.
- **Optional filters:**
  - `last_change_date` — tz-aware UTC cursor for delta queries.
- **Deferred filters** (rejected by `extra='forbid'` if attempted): `hire_date_code`, `activation_date_code`, `deactivation_date_code`, `termination_date_code`. Pending a unified date-code abstraction.
- **Refresh mode:** incremental.

### Response fields

| Wire name | Python attribute | Type | Description | Notes |
|---|---|---|---|---|
| `contactActivationDate` | `activation_date` | `datetime \| None` | Date the contact was activated | — |
| `contactAddress1` | `address_1` | `str \| None` | Contact mailing address line 1 | — |
| `contactAddress2` | `address_2` | `str \| None` | Contact mailing address line 2 | — |
| `contactAddress3` | `address_3` | `str \| None` | Contact mailing address line 3 | — |
| `contactAuxData1`–`contactAuxData14` | `aux_data_1`–`aux_data_14` | `str \| None` | Holman-defined auxiliary data fields | Free-text per tenant |
| `contactAuxDate1`–`contactAuxDate4` | `aux_date_1`–`aux_date_4` | `datetime \| None` | Holman-defined auxiliary date fields | — |
| `contactCellAcceptsText` | `cell_accepts_text` | `bool \| None` | Whether the cell phone accepts SMS | Coerced from `"Y"`/`"N"` wire strings |
| `contactCellPhone` | `cell_phone` | `str \| None` | Contact cell phone | — |
| `city` | `city` | `str \| None` | Contact mailing city | — |
| `country` | `country` | `str \| None` | Contact mailing country | — |
| `county` | `county` | `str \| None` | Contact mailing county | — |
| `contactData1`–`contactData7` | `data_1`–`data_7` | `str \| None` | Client-defined custom fields | Free-text per tenant; `data_2` modeled defensively despite Holman omitting it from sample responses |
| `contactDeactivationDate` | `deactivation_date` | `datetime \| None` | Date the contact was deactivated | — |
| `contactEmail` | `email` | `str \| None` | Contact email address | — |
| `contactEmployeeId` | `employee_id` | `str \| None` | Client-side employee identifier | Identifier |
| `contactFirstName` | `first_name` | `str \| None` | Contact first name | — |
| `contactHireDate` | `hire_date` | `datetime \| None` | Hire date | — |
| `contactHomePhone` | `home_phone` | `str \| None` | Contact home phone | — |
| `languagePreference` | `language_preference` | `str \| None` | Locale tag — e.g., `"en-US"` | — |
| `lastChangeDate` | `last_change_date` | `datetime \| None` | Watermark for incremental refresh | Cursor field |
| `lastChangeRecordId` | `last_change_record_id` | `int \| None` | Holman's monotonic change-id companion | — |
| `contactLastName` | `last_name` | `str \| None` | Contact last name | — |
| `contactMiddleName` | `middle_name` | `str \| None` | Contact middle name | — |
| `stateProvince` | `state_province` | `str \| None` | Contact mailing state / province | — |
| `contactStatus` | `status` | `str \| None` | Status free-text — e.g., `"ACTIVATED"` | — |
| `supervisorEmail` | `supervisor_email` | `str \| None` | Supervisor email address | — |
| `contactTerminationDate` | `termination_date` | `datetime \| None` | Termination date | — |
| `contactWorkPhone` | `work_phone` | `str \| None` | Contact work phone | — |
| `contactWorkPhoneExtension` | `work_phone_extension` | `str \| None` | Contact work phone extension | — |
| `zipPostalCode` | `zip_postal_code` | `str \| None` | Contact mailing ZIP / postal code | — |

## odometer

Latest odometer reading per vehicle. Snapshot-only; one record per vehicle, not a history.

### Request

- **URL path:** `/CustomerDataAPI/odometer/basic-query`
- **Required parameters:** `lessee_codes`; `paging`.
- **Filters:** none today. `last_change_date` is intentionally not exposed — Holman's odometer endpoint silently hangs until timeout when the parameter is sent. Incremental pulls against this endpoint use `last_change_record_id` instead, but pyholman currently treats odometer as snapshot-only.
- **Refresh mode:** snapshot.

### Response fields

| Wire name | Python attribute | Type | Description | Notes |
|---|---|---|---|---|
| `clientVehicleNumber` | `client_vehicle_number` | `str \| None` | Vehicle number assigned by the client | Identifier |
| `division` | `division` | `str \| None` | Holman division code | Code |
| `holmanVehicleNumber` | `holman_vehicle_number` | `str \| None` | Holman's internal vehicle identifier | Identifier |
| `icnNo` | `icn_no` | `int \| None` | Holman's internal numeric identifier per reading | — |
| `lastChangeDate` | `last_change_date` | `datetime \| None` | Wire-side change timestamp | Not used as watermark for this snapshot endpoint |
| `lastChangeRecordId` | `last_change_record_id` | `int \| None` | Wire-side monotonic change-id | Not used as cursor for this snapshot endpoint |
| `lesseeCode` | `lessee_code` | `str \| None` | 4-character lessee scope identifier | Identifier |
| `odometer` | `odometer` | `int \| None` | Latest odometer reading | — |
| `odometerDate` | `odometer_date` | `datetime \| None` | Date of the reading | — |
| `odometerHistoryId` | `odometer_history_id` | `int \| None` | Holman's per-reading history identifier | — |
| `odometerQuality` | `odometer_quality` | `str \| None` | Reading quality code | Code |
| `odometerSource` | `odometer_source` | `str \| None` | Reading source code — e.g., `"SMSR"` | Code |
| `prefix` | `prefix` | `str \| None` | Client-defined custom field (4-character) | — |
| `vehicleId` | `vehicle_id` | `int \| None` | Holman's internal numeric vehicle identifier | — |
| `vin` | `vin` | `str \| None` | Vehicle Identification Number | Identifier; length and content vary by asset (older equipment, trailers, and non-VIN identifiers may be shorter) |

## engine_hours

Latest engine-hour reading per vehicle. Snapshot-only; one record per vehicle. Mirrors odometer in shape and role minus `odometer_quality`.

### Request

- **URL path:** `/CustomerDataAPI/engine-hours/basic-query`
- **Required parameters:** `lessee_codes`; `paging`.
- **Filters:** none today. `last_change_date` is intentionally not exposed pending verification that Holman's engine-hours endpoint does not exhibit the same silent-hang behavior the odometer endpoint does on that parameter.
- **Refresh mode:** snapshot.

### Response fields

Holman's wire format mixes the casing of the `hour*meter*` fields within a single response — three use lowercase `m` (`hourmeter`, `hourmeterDate`, `hourmeterSource`) and one uses uppercase `M` (`hourMeterHistoryId`). The Pydantic aliases match the wire literally; the Python attribute names normalize to consistent snake_case.

| Wire name | Python attribute | Type | Description | Notes |
|---|---|---|---|---|
| `clientVehicleNumber` | `client_vehicle_number` | `str \| None` | Vehicle number assigned by the client | Identifier |
| `division` | `division` | `str \| None` | Holman division code | Code |
| `holmanVehicleNumber` | `holman_vehicle_number` | `str \| None` | Holman's internal vehicle identifier | Identifier |
| `hourmeter` | `hour_meter` | `int \| None` | Latest engine-hour reading | Wire alias is lowercase `m` |
| `hourmeterDate` | `hour_meter_date` | `datetime \| None` | Date of the reading | Wire alias is lowercase `m` |
| `hourMeterHistoryId` | `hour_meter_history_id` | `int \| None` | Holman's per-reading history identifier | Wire alias is uppercase `M` |
| `hourmeterSource` | `hour_meter_source` | `str \| None` | Reading source code — e.g., `"SMSR"` | Wire alias is lowercase `m`; code |
| `icnNo` | `icn_no` | `int \| None` | Holman's internal numeric identifier per reading | — |
| `lastChangeDate` | `last_change_date` | `datetime \| None` | Wire-side change timestamp | Not used as watermark for this snapshot endpoint |
| `lastChangeRecordId` | `last_change_record_id` | `int \| None` | Wire-side monotonic change-id | Not used as cursor for this snapshot endpoint |
| `lesseeCode` | `lessee_code` | `str \| None` | 4-character lessee scope identifier | Identifier |
| `prefix` | `prefix` | `str \| None` | Client-defined custom field (4-character) | — |
| `vehicleId` | `vehicle_id` | `int \| None` | Holman's internal numeric vehicle identifier | — |
| `vin` | `vin` | `str \| None` | Vehicle Identification Number | Identifier; length and content vary by asset (older equipment, trailers, and non-VIN identifiers may be shorter) |

## Common fields

`last_change_date` and `last_change_record_id` appear on every endpoint and serve the watermark / cursor role for incremental refresh on the three endpoints that support it (vehicles, maintenance_purchase_orders, contacts). pyholman manages the cursor automatically; consumers do not manipulate it directly. On the two snapshot endpoints (odometer, engine_hours), the fields are still present on the wire but are not used by pyholman as cursors.

## Type coercion

pyholman applies `mode='before'` field validators on a handful of vehicles and contacts fields where Holman's wire type does not match the value's content semantics — `"104623"` becomes `104623`, `"Y"` becomes `True`, `"32692.24"` becomes `32692.24`. The validators live on the affected response models themselves; the typed attribute on the parsed model carries the cleaned value, and the DataFrame conversion path uses pandas extension dtypes (`Int64`, `Float64`, `StringDtype`, `BooleanDtype`, `DatetimeTZDtype`) so missing values render as `pd.NA` uniformly.

## Whitespace and empty strings

Two normalizations apply uniformly across every endpoint:

- **Whitespace stripping** runs at the model layer via a `@model_validator(mode='before')` on `ResponseModel`. Every string-valued input has its leading and trailing whitespace removed before any field validator runs. `"            60250"` arrives at the model as `"60250"`; `"120 "` as `"120"`.
- **Empty-string-to-NA** runs at the DataFrame layer in `build_dataframe_from_records`. Every `StringDtype` column has its `""` values replaced with `pd.NA` before the DataFrame is returned. The Pydantic models faithfully preserve `""` from the wire; the DataFrame is the artifact where every dtype's missing-value representation becomes uniform.

## Sentinel handling

Holman uses JSON `null` for missing query-response values. The `^NULL^` sentinel mentioned in their PDF documentation is for SUBMIT requests, which pyholman does not expose.
