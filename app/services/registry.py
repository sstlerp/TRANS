"""Declarative screen registry: one MasterSpec per master/transaction screen.

Business dropdowns use configurable lookups (`type="lookup"`); `choices` are
only used for technical enums whose values drive program logic.
"""
from __future__ import annotations

from sqlalchemy import delete, insert, select

from app.core.audit import audit
from app.core.errors import BusinessError
from app.core.security import hash_password, validate_password_strength
from app.core.utils import now
from app.models import compliance as C
from app.models import finance as FI
from app.models import fleet as FL
from app.models import imports as IM
from app.models import operations as OP
from app.models import org as O
from app.models import system as S
from app.models import tyres as TY
from app.services import (bank, contracts, import_engine, maintenance, operations, renewals, tyres, vehicles)
from app.services.masters import Action, Child, F, MasterSpec, register

ACTIVE_INACTIVE = None
PROVIDER_TYPES = ["BANK", "TOLL", "FUEL", "INSURANCE", "MAINTENANCE", "GPS", "TELEMATICS", "OTHER"]
STATEMENT_TYPES = ["BANK", "TOLL", "FASTAG", "FUEL", "FUEL_CARD", "MAINTENANCE", "INSURANCE", "GPS", "TELEMATICS"]
CC_TYPES = ["VEHICLE", "NON_VEHICLE", "COMMON", "CONTRACT", "OTHER"]
ATTR_TYPES = ["TEXT", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DROPDOWN"]
RENEWAL_STATUS = ["NOT_DUE", "UPCOMING", "DUE", "EXPIRED", "RENEWED", "CANCELLED", "NOT_APPLICABLE"]
PAY_STATUS = ["PENDING", "PAID", "NOT_APPLICABLE"]
REPORT_GROUPS = ["FUEL", "TOLL", "MAINTENANCE", "TYRE", "INSURANCE", "TAX", "PERMIT", "PESO", "DRIVER", "VENDOR",
                 "OTHER_DIRECT", "COMMON", "ASSET", "LOAN", "BANK_CHARGE", "OTHER"]
TREATMENTS = ["OPERATING_INCOME", "OTHER_INCOME", "EXPENSE_REDUCTION", "NON_OPERATING", "BALANCE_SHEET", "SETTLEMENT",
              "EXCLUDE"]
LINK_TYPES = list(bank.LINK_RULES)
TYRE_STATUS = ["NEW", "IN_STOCK", "INSTALLED", "SHIFTED", "REMOVED", "IN_GODOWN", "SENT_FOR_RETREADING", "RETREADED",
               "FITTED_AFTER_RETREAD", "UNDER_INSPECTION", "DAMAGED", "WARRANTY", "SCRAPPED", "SOLD", "LOST"]
FUEL_STATUS = ["IMPORTED", "VALIDATED", "VEHICLE_UNMATCHED", "FLAGGED", "OVERRIDDEN", "ERROR", "CANCELLED"]
TOLL_STATUS = ["IMPORTED", "VEHICLE_MATCHED", "VEHICLE_UNMATCHED", "PLAZA_MATCHED", "PLAZA_UNMATCHED", "DUPLICATE",
               "VALIDATED", "ERROR"]
RECON_STATUS = ["UNMATCHED", "PARTIALLY_MATCHED", "MATCHED", "ALLOCATED", "AUTO_SUGGESTED", "PENDING_APPROVAL",
                "REJECTED", "IGNORED", "REVERSED"]
SOURCE_TYPES = ["EXCEL", "API", "MANUAL", "SYSTEM"]
EVENT_TYPES = ["RENEWAL_DUE", "RENEWAL_EXPIRED", "INSURANCE_EXPIRY", "PERMIT_EXPIRY", "FITNESS_EXPIRY", "PUCC_EXPIRY",
               "PESO_EXPIRY", "DRIVER_LICENSE_EXPIRY", "UNMATCHED_BANK", "IMPORT_ERRORS", "FUEL_UNUSUAL",
               "TYRE_TREAD_LOW", "TYRE_WARRANTY", "MAINTENANCE_DUE", "APPROVAL_PENDING"]
APPROVAL_ACTIONS = ["BANK_ALLOCATION", "BANK_MATCH", "LARGE_TRANSACTION", "ODOMETER_OVERRIDE", "FUEL_OVERRIDE",
                    "TYRE_CORRECTION", "MASTER_CHANGE", "RENEWAL_UPDATE"]


def cc_from_vehicle(date_attr: str):
    """Child-row hook: derive the cost center from the vehicle as at the parent's date (history-aware)."""
    def _prep(ctx, parent, kid):
        if getattr(kid, "vehicle_id", None) and not getattr(kid, "cost_center_id", None):
            kid.cost_center_id = vehicles.cost_center_for(ctx.db, kid.vehicle_id, getattr(parent, date_attr, None))
        if not getattr(kid, "cost_center_id", None):
            raise BusinessError("Each allocation line needs a vehicle or a cost center")
    return _prep


def code(maxlen=20, label="Code"):
    return F("code", label, required=True, upper=True, maxlen=maxlen, list=True, search=True,
             pattern=r"[A-Z0-9_\-/#. ]+", pattern_msg="letters, digits, _ - / # . only")


def name(maxlen=150, label="Name"):
    return F("name", label, required=True, maxlen=maxlen, list=True, search=True)


def remarks(n="remarks", label="Remarks"):
    return F(n, label, type="textarea", span=3, section="Remarks")


# ═════════════════════════════ ORGANISATION ═════════════════════════════
register(MasterSpec("companies", O.Company, "Companies", "org", "ti-building", [
    code(), name(200), F("legal_name", "Legal Name", maxlen=255),
    F("gstin", "GSTIN", upper=True, maxlen=15, pattern=r"\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]", pattern_msg="invalid GSTIN", list=True),
    F("pan", "PAN", upper=True, maxlen=10, pattern=r"[A-Z]{5}\d{4}[A-Z]", pattern_msg="format ABCDE1234F"),
    F("state_id", "State", type="fk", fk="states"), F("phone", "Phone", maxlen=20), F("email", "E-mail", maxlen=150),
    F("timezone", "Timezone", default="Asia/Kolkata", maxlen=50), F("currency", "Currency", default="INR", maxlen=3),
    F("address", "Address", type="textarea", span=3)], group="Organization", documents=True))

register(MasterSpec("states", O.State, "States", "org", "ti-map", [
    F("code", "Code", required=True, upper=True, maxlen=5, list=True, search=True), name(100),
    F("gst_code", "GST State Code", maxlen=2, list=True, pattern=r"\d{2}", pattern_msg="2 digits")],
    group="Organization", default_sort="name", default_dir="asc"))

register(MasterSpec("districts", O.District, "Districts", "org", "ti-map-2", [
    F("state_id", "State", type="fk", fk="states", required=True, list=True, filter=True), name(100),
    F("code", "Code", upper=True, maxlen=20, list=True)], group="Organization", label_fields=("name",),
    default_sort="name", default_dir="asc"))

register(MasterSpec("rtos", O.Rto, "RTOs", "org", "ti-building-community", [
    F("code", "RTO Code", required=True, upper=True, maxlen=10, list=True, search=True), name(150),
    F("state_id", "State", type="fk", fk="states", list=True, filter=True),
    F("district_id", "District", type="fk", fk="districts", depends_on="state_id")], group="Organization"))

register(MasterSpec("branches", O.Branch, "Branches", "org", "ti-building-store", [
    F("company_id", "Company", type="fk", fk="companies", required=True, list=True, filter=True), code(), name(),
    F("state_id", "State", type="fk", fk="states", list=True),
    F("district_id", "District", type="fk", fk="districts", depends_on="state_id"),
    F("gstin", "GSTIN", upper=True, maxlen=15), F("phone", "Phone", maxlen=20), F("email", "E-mail", maxlen=150),
    F("address", "Address", type="textarea", span=3)], group="Organization", branch_field=None))

register(MasterSpec("departments", O.Department, "Departments", "org", "ti-sitemap", [
    code(), name(), F("branch_id", "Branch", type="fk", fk="branches", list=True, filter=True)],
    group="Organization", branch_field="branch_id"))

register(MasterSpec("locations", O.Location, "Locations / Godowns / Workshops / Warehouses", "org", "ti-map-pin", [
    code(), name(), F("location_type", "Type", type="lookup", lookup="LOCATION_TYPE", required=True, list=True, filter=True),
    F("branch_id", "Branch", type="fk", fk="branches", list=True, filter=True),
    F("state_id", "State", type="fk", fk="states"), F("district_id", "District", type="fk", fk="districts", depends_on="state_id"),
    F("pincode", "Pincode", maxlen=6, pattern=r"\d{6}", pattern_msg="6 digits"),
    F("contact_person", "Contact Person", maxlen=100), F("phone", "Phone", maxlen=20),
    F("address", "Address", type="textarea", span=3)], group="Organization", branch_field="branch_id"))

# ═════════════════════════════ CONFIGURATION MASTERS ═════════════════════════════
register(MasterSpec("lookup_values", O.LookupValue, "Lookup Values (dropdown configuration)", "master", "ti-list-details", [
    F("category", "Category", required=True, upper=True, maxlen=50, list=True, search=True, filter=True),
    F("code", "Code", required=True, upper=True, maxlen=50, list=True, search=True),
    F("label", "Label", required=True, maxlen=150, list=True, search=True),
    F("sort_order", "Sort Order", type="int", default=0, list=True),
    F("description", "Description", maxlen=255)], group="Administration", label_fields=("label",),
    default_sort="category", default_dir="asc"))

register(MasterSpec("units", O.Unit, "Units", "master", "ti-ruler-measure", [
    code(), name(60), F("unit_type", "Unit Type", type="select", choices=["VOLUME", "MASS", "ENERGY", "LENGTH", "COUNT", "TIME", "OTHER"],
                        required=True, list=True, filter=True)], group="Administration"))

register(MasterSpec("cost_categories", FL.CostCategory, "Cost Categories", "master", "ti-category", [
    code(), name(100), F("applies_to", "Applies To", type="select", choices=["VEHICLE", "NON_VEHICLE", "BOTH"],
                         default="VEHICLE", required=True, list=True, filter=True),
    F("description", "Description", maxlen=255, span=2)], group="Fleet",
    description="e.g. Truck, Trailer (vehicle) or Administration, Workshop (non-vehicle)."))

register(MasterSpec("sub_categories", FL.VehicleSubCategory, "Vehicle Sub-categories", "master", "ti-category-2", [
    F("cost_category_id", "Cost Category", type="fk", fk="cost_categories", required=True, list=True, filter=True), code(),
    name(100), F("default_tyre_layout_id", "Default Tyre Layout", type="fk", fk="tyre_layouts", list=True),
    F("description", "Description", maxlen=255, span=2)], group="Fleet",
    description="e.g. LPG, Open Body, Container. Technical attributes are configured per sub-category."))

register(MasterSpec("sub_category_attributes", FL.SubCategoryAttribute, "Sub-category Attributes", "master", "ti-adjustments", [
    F("sub_category_id", "Sub-category", type="fk", fk="sub_categories", required=True, list=True, filter=True),
    F("code", "Code", required=True, upper=True, maxlen=40, list=True, search=True), name(100, "Attribute Name"),
    F("data_type", "Data Type", type="select", choices=ATTR_TYPES, required=True, list=True),
    F("unit_id", "Unit", type="fk", fk="units", list=True), F("is_mandatory", "Mandatory", type="bool", list=True),
    F("display_order", "Display Order", type="int", default=0, list=True),
    F("min_value", "Min", type="decimal"), F("max_value", "Max", type="decimal"),
    F("dropdown_options", "Dropdown Options (comma/line separated)", type="textarea", span=3)],
    group="Fleet", default_sort="display_order", default_dir="asc"))

register(MasterSpec("cost_centers", FL.CostCenter, "Cost Centers", "master", "ti-target", [
    code(30), name(), F("cc_type", "Type", type="select", choices=CC_TYPES, required=True, list=True, filter=True),
    F("cost_category_id", "Cost Category", type="fk", fk="cost_categories", list=True, filter=True),
    F("branch_id", "Branch", type="fk", fk="branches", list=True, filter=True),
    F("department_id", "Department", type="fk", fk="departments"),
    F("parent_id", "Parent Cost Center", type="fk", fk="cost_centers"),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", readonly=True, list=True),
    F("description", "Description", maxlen=255, span=2)], group="Fleet", branch_field="branch_id",
    description="Vehicle cost centers are created automatically with each vehicle."))

register(MasterSpec("fuel_types", FL.FuelType, "Fuel Types", "master", "ti-gas-station", [
    code(), name(60), F("default_unit_id", "Default Unit", type="fk", fk="units", list=True),
    F("efficiency_label", "Efficiency Label (KM/L …)", maxlen=20, list=True),
    F("min_efficiency", "Min Normal Efficiency", type="decimal", hint="below → flagged unusual"),
    F("max_efficiency", "Max Normal Efficiency", type="decimal", hint="above → flagged unusual")], group="Fuel"))

register(MasterSpec("renewal_types", C.RenewalType, "Renewal Types", "master", "ti-certificate", [
    code(30), name(), F("category", "Category", type="lookup", lookup="RENEWAL_CATEGORY", required=True, list=True, filter=True),
    F("applies_to", "Applies To", type="select", choices=["VEHICLE", "DRIVER", "COMPANY"], default="VEHICLE", list=True),
    F("expense_type_id", "Expense Type", type="fk", fk="expense_types"),
    F("requires_document", "Document Required", type="bool", default=True, list=True),
    F("allows_multiple", "Multiple per Vehicle", type="bool", list=True),
    F("default_validity_months", "Default Validity (months)", type="int"),
    F("default_reminder_days", "Reminder Days", hint="e.g. 60,30,15,7,1,0", maxlen=100),
    F("description", "Description", maxlen=255, span=2)], group="Compliance"))

register(MasterSpec("renewal_rules", C.RenewalRule, "Renewal Rules", "master", "ti-git-branch", [
    code(30), name(), F("renewal_type_id", "Renewal Type", type="fk", fk="renewal_types", required=True, list=True, filter=True),
    F("cost_category_id", "Only Category", type="fk", fk="cost_categories", list=True),
    F("sub_category_id", "Only Sub-category", type="fk", fk="sub_categories", list=True, depends_on="cost_category_id"),
    F("fuel_type_id", "Only Fuel Type", type="fk", fk="fuel_types"),
    F("instances_required", "Certificates Required", type="int", default=1, min=1, list=True,
      hint="e.g. 2 PESO certificates"),
    F("is_mandatory", "Mandatory", type="bool", default=True), F("validity_months", "Validity (months)", type="int"),
    F("reminder_days", "Reminder Days", maxlen=100, hint="blank = type/global default"),
    F("grace_days", "Grace Days", type="int", default=0), F("description", "Description", maxlen=255, span=2)],
    actions=[Action("apply", "Apply to fleet", "ti-player-play", "master.edit", renewals.apply_rule_to_fleet,
                    confirm="Create missing renewal slots on all matching vehicles?")], group="Compliance"))

register(MasterSpec("tyre_positions", TY.TyrePosition, "Tyre Positions", "master", "ti-circle-dot", [
    code(), name(100), F("axle_number", "Axle", type="int", list=True),
    F("side", "Side", type="select", choices=["LEFT", "RIGHT", "CENTER"], list=True),
    F("placement", "Placement", type="select", choices=["SINGLE", "OUTER", "INNER"], list=True),
    F("position_type", "Position Type", type="select", choices=["STEER", "DRIVE", "TAG", "LIFT", "TRAILER", "SPARE"], list=True),
    F("display_order", "Display Order", type="int", default=0)], group="Tyres", default_sort="display_order",
    default_dir="asc"))

register(MasterSpec("tyre_layouts", TY.TyreLayout, "Vehicle Tyre Layouts", "master", "ti-layout-grid", [
    code(), name(100), F("axle_count", "Axles", type="int", list=True), F("description", "Description", maxlen=255, span=2)],
    children=[Child("positions", "Positions", TY.VehicleTyrePositionConfiguration, "layout_id", [
        F("position_id", "Position", type="fk", fk="tyre_positions", required=True),
        F("display_row", "Row (axle)", type="int", required=True, default=1),
        F("display_col", "Column", type="int", required=True, default=1), F("is_spare", "Spare", type="bool")],
        order_by="display_row", min_rows=1)], group="Tyres",
    description="vehicle_tyre_position_configurations: positions per layout and their place on the tyre dashboard."))

register(MasterSpec("tyre_locations", TY.TyreLocation, "Tyre Locations", "master", "ti-building-warehouse", [
    code(), name(), F("location_type", "Type", type="select",
                      choices=["GODOWN", "WORKSHOP", "RETREADER", "SCRAP_YARD", "VENDOR", "WARRANTY", "OTHER"],
                      required=True, list=True, filter=True),
    F("location_id", "Physical Location", type="fk", fk="locations"), F("vendor_id", "Vendor", type="fk", fk="vendors"),
    F("branch_id", "Branch", type="fk", fk="branches", list=True)], group="Tyres"))

register(MasterSpec("maintenance_types", OP.MaintenanceType, "Maintenance Types", "master", "ti-tool", [
    code(30), name(100), F("category", "Category", type="lookup", lookup="MAINTENANCE_CATEGORY", required=True, list=True, filter=True),
    F("interval_km", "Service Interval (km)", type="int", list=True), F("interval_days", "Service Interval (days)", type="int", list=True),
    F("description", "Description", maxlen=255, span=2)], group="Maintenance"))

register(MasterSpec("credit_types", FI.CreditType, "Credit Types", "master", "ti-arrow-down-left", [
    code(30), name(100), F("accounting_treatment", "Accounting Treatment", type="select", choices=TREATMENTS, required=True,
                           list=True, filter=True),
    F("default_link_type", "Default Link Type", type="select", choices=LINK_TYPES, list=True),
    F("requires_link", "Must Link to Original", type="bool"), F("description", "Description", maxlen=255, span=2)],
    group="Finance", description="Bank credits stay UNCLASSIFIED until a user classifies/matches them."))

register(MasterSpec("expense_types", FI.ExpenseType, "Expense Types", "master", "ti-arrow-up-right", [
    code(30), name(100), F("report_group", "Report Group", type="select", choices=REPORT_GROUPS, required=True, list=True,
                           filter=True),
    F("is_operating", "Operating Cost", type="bool", default=True, list=True,
      hint="off for capex / loans / balance-sheet items"), F("description", "Description", maxlen=255, span=2)],
    group="Finance"))

register(MasterSpec("transaction_types", FI.TransactionType, "Transaction Types", "master", "ti-arrows-exchange", [
    code(30), name(100), F("module", "Module", required=True, upper=True, maxlen=30, list=True, filter=True),
    F("direction", "Direction", type="select", choices=["CR", "DR", "NA"], list=True),
    F("description", "Description", maxlen=255, span=2)], group="Finance"))

register(MasterSpec("matching_rules", FI.MatchingRule, "Matching Rules", "master", "ti-arrows-join", [
    code(30), name(), F("link_type", "Link Type", type="select", choices=LINK_TYPES, required=True, list=True, filter=True),
    F("priority", "Priority", type="int", default=100, list=True),
    F("date_tolerance_days", "Date Tolerance (days)", type="int", default=3),
    F("amount_tolerance", "Amount Tolerance (₹)", type="money", default=0),
    F("match_on_amount", "Amount", type="bool", default=True), F("match_on_utr", "UTR", type="bool", default=True),
    F("match_on_reference", "Reference", type="bool", default=True),
    F("match_on_party_name", "Party Name", type="bool", default=True),
    F("narration_keywords", "Narration Keywords (comma separated)", maxlen=500, span=2),
    F("min_score", "Min Score to Suggest", type="int", default=50, list=True),
    F("auto_approve", "Auto-approve", type="bool", list=True, hint="only when explicitly allowed"),
    F("auto_approve_min_score", "Auto-approve Min Score", type="int", default=95),
    F("description", "Description", maxlen=255, span=2)], group="Finance"))

register(MasterSpec("providers", O.Provider, "Providers (Bank / Toll / Fuel / Insurance / Service)", "master", "ti-plug", [
    code(30), name(200), F("provider_type", "Provider Type", type="select", choices=PROVIDER_TYPES, required=True, list=True,
                           filter=True),
    F("vendor_id", "Linked Vendor", type="fk", fk="vendors"), F("contact_person", "Contact", maxlen=100),
    F("phone", "Phone", maxlen=20), F("email", "E-mail", maxlen=150), F("website", "Website", maxlen=200),
    remarks()], group="Imports"))

register(MasterSpec("value_mappings", IM.ValueMapping, "Value Mappings (fuel / provider / vehicle / plaza)", "master",
                    "ti-replace", [
    F("mapping_type", "Mapping Type", type="select", choices=["FUEL_TYPE", "PROVIDER", "VEHICLE", "TOLL_PLAZA",
                                                               "FUEL_STATION", "GENERIC"], required=True, list=True, filter=True),
    F("provider_id", "Provider (blank = all)", type="fk", fk="providers", list=True, filter=True),
    F("source_value", "Source Value", required=True, maxlen=150, list=True, search=True),
    F("target_value", "Target Code / Value", maxlen=150, list=True),
    F("target_id", "Target Record ID", type="int", list=True, hint="vehicle / plaza / station id"),
    F("remarks", "Remarks", maxlen=255)], group="Imports", label_fields=("source_value",)))

register(MasterSpec("business_rules", S.BusinessRule, "System Settings / Business Rules", "admin", "ti-settings", [
    F("rule_key", "Key", required=True, upper=True, maxlen=80, list=True, search=True, readonly_on_edit=True),
    F("module", "Module", required=True, upper=True, maxlen=30, list=True, filter=True),
    F("value", "Value", required=True, maxlen=500, list=True),
    F("value_type", "Type", type="select", choices=["STRING", "INT", "DECIMAL", "BOOL", "LIST", "CHOICE"], list=True),
    F("choices", "Allowed Choices", maxlen=255), F("description", "Description", maxlen=500, span=2, list=True)],
    group="Administration", label_fields=("rule_key",), default_sort="module", default_dir="asc", can_delete=False))


def _rule_validate(ctx, r: S.BusinessRule, data, is_new):
    from app.services.rules import _cast
    try:
        _cast(r.value, r.value_type)
    except Exception as exc:  # noqa: BLE001
        raise BusinessError(f"Value is not a valid {r.value_type}") from exc
    if r.value_type == "CHOICE" and r.choices and r.value not in r.choices.split(","):
        raise BusinessError(f"Value must be one of {r.choices}")


from app.services.masters import REGISTRY as _R  # noqa: E402
_R["business_rules"].before_save = _rule_validate

register(MasterSpec("notification_rules", S.NotificationRule, "Notification Rules", "admin", "ti-bell-cog", [
    code(40), name(), F("event_type", "Event", type="select", choices=EVENT_TYPES, required=True, list=True, filter=True),
    F("channels", "Channels", default="IN_APP", maxlen=100, list=True, hint="IN_APP,EMAIL (SMS/WHATSAPP future)"),
    F("days_before", "Days Before", maxlen=100), F("severity", "Severity", type="select", choices=["INFO", "WARNING", "CRITICAL"],
                                                   default="WARNING", list=True),
    F("recipient_role_id", "Recipient Role", type="fk", fk="roles"),
    F("recipient_emails", "E-mail Recipients", maxlen=500, span=2), F("description", "Description", maxlen=255, span=2)],
    group="Administration"))

register(MasterSpec("approval_rules", FI.ApprovalRule, "Approval Rules", "admin", "ti-checklist", [
    code(30), name(), F("action_type", "Action", type="select", choices=APPROVAL_ACTIONS, required=True, list=True, filter=True),
    F("min_amount", "Applies From Amount (₹)", type="money", list=True, hint="blank = always"),
    F("levels", "Approval Levels", type="int", default=1, min=1, max=5, list=True),
    F("approver_permission", "Approver Permission", default="approval.approve", maxlen=80),
    F("allow_self_approval", "Allow Self-approval", type="bool"), F("description", "Description", maxlen=255, span=2)],
    group="Administration"))

register(MasterSpec("api_integrations", OP.ApiIntegration, "API Integrations (Toll / Fuel / Bank / GPS)", "admin", "ti-api", [
    code(30), name(), F("integration_type", "Type", type="select",
                        choices=PROVIDER_TYPES + ["FASTAG", "ACCOUNTING", "GOVT", "TOLL_PLAZA_MASTER"],
                        required=True, list=True, filter=True),
    F("provider_id", "Provider", type="fk", fk="providers", list=True), F("base_url", "Base URL", maxlen=255, span=2),
    F("auth_type", "Auth", type="select", choices=["NONE", "API_KEY", "BASIC", "OAUTH2"]),
    F("credential_env_var", "Credential Env Variable", maxlen=100, pattern=r"[A-Z][A-Z0-9_]*",
      pattern_msg="name of an environment variable, e.g. ERP_FASTAG_API_KEY — never the secret itself"),
    F("client_id_env_var", "Client-ID Env Variable", maxlen=100, pattern=r"[A-Z][A-Z0-9_]*",
      pattern_msg="environment variable name"),
    F("timeout_seconds", "Timeout (s)", type="int", default=30),
    F("sync_frequency_minutes", "Sync Every (min)", type="int"),
    F("last_sync_at", "Last Sync", type="datetime", readonly=True, list=True),
    F("last_sync_status", "Last Status", readonly=True, list=True), F("remarks", "Remarks", maxlen=255, span=2),
    F("settings", "Settings (JSON)", type="json", span=3,
      hint="e.g. adapter, resource_id, records_path, field_map — see docs/INTEGRATIONS.md")],
    group="Administration", description="Secrets are read from environment variables at runtime and never stored."))

# ═════════════════════════════ PARTIES ═════════════════════════════
register(MasterSpec("vendors", O.Vendor, "Vendors / Suppliers / Service Providers", "vendor", "ti-truck-delivery", [
    code(), name(200), F("vendor_type", "Vendor Type", type="lookup", lookup="VENDOR_TYPE", required=True, list=True, filter=True),
    F("gstin", "GSTIN", upper=True, maxlen=15, list=True), F("pan", "PAN", upper=True, maxlen=10),
    F("contact_person", "Contact", maxlen=100), F("phone", "Phone", maxlen=20, list=True), F("email", "E-mail", maxlen=150),
    F("state_id", "State", type="fk", fk="states"), F("payment_terms_days", "Payment Terms (days)", type="int"),
    F("bank_name", "Bank", maxlen=150, section="Bank"), F("bank_account_no", "Account No.", maxlen=30, section="Bank"),
    F("bank_ifsc", "IFSC", upper=True, maxlen=11, section="Bank", pattern=r"[A-Z]{4}0[A-Z0-9]{6}", pattern_msg="invalid IFSC"),
    F("match_keywords", "Bank Narration Keywords", maxlen=255, span=2, hint="used for bank matching suggestions"),
    F("address", "Address", type="textarea", span=3), remarks()], group="Vendors", documents=True))

register(MasterSpec("customers", O.Customer, "Customers", "contract", "ti-users", [
    code(), name(200), F("gstin", "GSTIN", upper=True, maxlen=15, list=True), F("pan", "PAN", upper=True, maxlen=10),
    F("contact_person", "Contact", maxlen=100), F("phone", "Phone", maxlen=20, list=True), F("email", "E-mail", maxlen=150),
    F("state_id", "State", type="fk", fk="states"), F("credit_days", "Credit Days", type="int", list=True),
    F("credit_limit", "Credit Limit", type="money"),
    F("match_keywords", "Bank Narration Keywords", maxlen=255, span=2),
    F("billing_address", "Billing Address", type="textarea", span=3), remarks()], group="Contracts & Income",
    documents=True))

register(MasterSpec("banks", O.Bank, "Banks", "finance", "ti-building-bank", [
    code(), name(200), F("short_name", "Short Name", maxlen=30, list=True),
    F("provider_id", "Statement Provider", type="fk", fk="providers", fk_filter={"provider_type": "BANK"})], group="Finance"))

register(MasterSpec("bank_accounts", O.BankAccount, "Bank Accounts", "finance", "ti-credit-card", [
    F("bank_id", "Bank", type="fk", fk="banks", required=True, list=True, filter=True), code(),
    F("account_name", "Account Name", required=True, maxlen=200, list=True, search=True),
    F("account_number", "Account Number", required=True, maxlen=34, list=True, search=True),
    F("account_type", "Account Type", type="lookup", lookup="ACCOUNT_TYPE", required=True, list=True),
    F("company_id", "Company", type="fk", fk="companies"), F("branch_id", "Branch", type="fk", fk="branches", list=True),
    F("bank_branch", "Bank Branch", maxlen=150), F("ifsc", "IFSC", upper=True, maxlen=11, pattern=r"[A-Z]{4}0[A-Z0-9]{6}",
                                                   pattern_msg="invalid IFSC"),
    F("opening_balance", "Opening Balance", type="money", default=0), F("opening_date", "Opening Date", type="date"),
    F("closing_balance", "Closing Balance (last statement)", type="money", readonly=True, list=True),
    F("closing_balance_date", "As Of", type="date", readonly=True, list=True), remarks()],
    group="Finance", label_fields=("code", "account_name"), branch_field="branch_id"))

# ═════════════════════════════ FLEET ═════════════════════════════
VEHICLE_FIELDS = [
    F("vehicle_code", "Vehicle ID", required=True, upper=True, maxlen=30, list=True, search=True, section="Identity",
      readonly_on_edit=True),
    F("registration_number", "Registration No.", required=True, upper=True, maxlen=20, list=True, search=True, section="Identity"),
    F("fleet_number", "Fleet No.", upper=True, maxlen=30, list=True, search=True, section="Identity"),
    F("vehicle_type", "Vehicle Type", type="lookup", lookup="VEHICLE_TYPE", section="Identity"),
    F("chassis_number", "Chassis No.", upper=True, maxlen=30, search=True, section="Identity"),
    F("engine_number", "Engine No.", upper=True, maxlen=30, search=True, section="Identity"),
    F("cost_category_id", "Category", type="fk", fk="cost_categories", required=True, list=True, filter=True,
      readonly_on_edit=True, section="Classification", fk_filter={"applies_to": "VEHICLE,BOTH"}),
    F("sub_category_id", "Sub-category", type="fk", fk="sub_categories", required=True, list=True, filter=True,
      readonly_on_edit=True, depends_on="cost_category_id", section="Classification"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", readonly=True, list=True, section="Classification",
      hint="auto-created"),
    F("branch_id", "Branch", type="fk", fk="branches", list=True, filter=True, section="Classification"),
    F("location_id", "Location", type="fk", fk="locations", section="Classification"),
    F("rto_id", "RTO", type="fk", fk="rtos", section="Classification"),
    F("manufacturer", "Manufacturer", maxlen=100, section="Make & Ownership", list=True, filter=True),
    F("model", "Model", maxlen=100, section="Make & Ownership"),
    F("manufacturing_year", "Mfg Year", type="int", min=1950, max=2100, section="Make & Ownership"),
    F("purchase_date", "Purchase Date", type="date", section="Make & Ownership"),
    F("purchase_cost", "Purchase Cost", type="money", section="Make & Ownership"),
    F("ownership_type", "Ownership", type="lookup", lookup="OWNERSHIP_TYPE", section="Make & Ownership"),
    F("owner_name", "Owner", maxlen=150, section="Make & Ownership"),
    F("vehicle_status", "Status", type="lookup", lookup="VEHICLE_STATUS", required=True, default="ACTIVE", list=True,
      filter=True, section="Capacity & Status"),
    F("capacity", "Capacity", type="decimal", section="Capacity & Status"),
    F("capacity_unit_id", "Capacity Unit", type="fk", fk="units", section="Capacity & Status"),
    F("gvw", "GVW (kg)", type="decimal", section="Capacity & Status"),
    F("axle_count", "Axles", type="int", min=1, max=12, section="Capacity & Status"),
    F("tyre_layout_id", "Tyre Layout", type="fk", fk="tyre_layouts", section="Capacity & Status"),
    F("current_odometer", "Current Odometer", type="decimal", readonly_on_edit=True, list=True, section="Capacity & Status",
      hint="later readings via Odometer action"),
    remarks(),
]
register(MasterSpec(
    "vehicles", FL.Vehicle, "Vehicle Master", "fleet", "ti-truck", VEHICLE_FIELDS,
    children=[Child("fuels", "Fuel Configuration", FL.VehicleFuel, "vehicle_id", [
        F("fuel_type_id", "Fuel Type", type="fk", fk="fuel_types", required=True),
        F("is_primary", "Primary", type="bool"), F("tank_capacity", "Tank / Cylinder Capacity", type="decimal"),
        F("effective_from", "From", type="date"), F("effective_to", "To", type="date"),
        F("is_active", "Active", type="bool", default=True)], min_rows=1)],
    actions=[
        Action("reclassify", "Change Category / Cost Center", "ti-arrows-shuffle", "fleet.reclassify", vehicles.reclassify, [
            F("effective_from", "Effective From", type="date", required=True),
            F("cost_category_id", "New Category", type="fk", fk="cost_categories", required=True),
            F("sub_category_id", "New Sub-category", type="fk", fk="sub_categories", required=True, depends_on="cost_category_id"),
            F("cost_center_id", "Cost Center (blank = keep)", type="fk", fk="cost_centers"),
            F("reason", "Reason", type="textarea", required=True)], reason_required=True),
        Action("odometer", "Record Odometer", "ti-gauge", "fleet.edit", vehicles.odometer_action, [
            F("reading", "Reading (km)", type="decimal", required=True, min=0),
            F("reading_at", "Date & Time", type="datetime"),
            F("reason", "Override Reason (if lower than previous)", type="textarea")]),
        Action("renewal_slots", "Apply Renewal Rules", "ti-certificate", "compliance.edit",
               lambda ctx, v, d: {"message": f"{vehicles.ensure_renewal_assignments(ctx, v)} new renewal slot(s)"}),
    ],
    title_field="registration_number", code_field="vehicle_code", label_fields=("registration_number", "vehicle_code"),
    before_save=vehicles.before_save, after_save=vehicles.after_save, branch_field="branch_id", documents=True,
    group="Fleet", status_field="vehicle_status", subtitle_fields=("fleet_number", "manufacturer", "model"),
    serialize_extra=lambda ctx, v, row: row.update(attributes=vehicles.attribute_values(ctx.db, v.id))))

register(MasterSpec("vehicle_cc_history", FL.VehicleCostCenterHistory, "Vehicle Cost Center History", "fleet", "ti-history", [
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, readonly=True),
    F("old_cost_category_id", "Old Category", type="fk", fk="cost_categories", list=True, readonly=True),
    F("new_cost_category_id", "New Category", type="fk", fk="cost_categories", list=True, readonly=True),
    F("old_sub_category_id", "Old Sub-category", type="fk", fk="sub_categories", list=True, readonly=True),
    F("new_sub_category_id", "New Sub-category", type="fk", fk="sub_categories", list=True, readonly=True),
    F("old_cost_center_id", "Old Cost Center", type="fk", fk="cost_centers", readonly=True),
    F("new_cost_center_id", "New Cost Center", type="fk", fk="cost_centers", list=True, readonly=True),
    F("effective_from", "From", type="date", list=True, readonly=True), F("effective_to", "To", type="date", list=True, readonly=True),
    F("reason", "Reason", list=True, readonly=True), F("changed_at", "Changed At", type="datetime", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Fleet",
    date_field="effective_from", branch_via_vehicle="vehicle_id"))

register(MasterSpec("odometer_readings", FL.OdometerReading, "Odometer Readings", "fleet", "ti-gauge", [
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, readonly=True),
    F("reading_at", "Date/Time", type="datetime", list=True, readonly=True),
    F("reading", "Reading", type="decimal", list=True, readonly=True),
    F("source_module", "Source", list=True, filter=True, readonly=True),
    F("is_override", "Override", type="bool", list=True, readonly=True),
    F("override_reason", "Override Reason", list=True, readonly=True), F("remarks", "Remarks", readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("reading",), group="Fleet",
    date_field="reading_at", default_sort="reading_at", branch_via_vehicle="vehicle_id"))

# ═════════════════════════════ DRIVERS ═════════════════════════════
def _driver_check(d: C.Driver) -> None:
    if d.license_issue_date and d.license_expiry_date and d.license_expiry_date <= d.license_issue_date:
        raise BusinessError("Licence expiry must be after the issue date")


register(MasterSpec("drivers", C.Driver, "Driver Master", "driver", "ti-steering-wheel", [
    F("driver_code", "Driver ID", required=True, upper=True, maxlen=30, list=True, search=True, section="Identity"),
    name(150, "Name"), F("employee_number", "Employee / Contract No.", upper=True, maxlen=30, list=True, search=True,
                         section="Identity"),
    F("date_of_birth", "Date of Birth", type="date", section="Identity"),
    F("mobile", "Mobile", maxlen=15, list=True, pattern=r"\+?\d{10,13}", pattern_msg="10-13 digits", section="Contact"),
    F("alt_mobile", "Alt. Mobile", maxlen=15, section="Contact"),
    F("address", "Address", type="textarea", span=2, section="Contact"),
    F("license_number", "Licence No.", upper=True, maxlen=30, list=True, search=True, section="Licence"),
    F("license_class", "Licence Class", type="lookup", lookup="LICENSE_CLASS", section="Licence"),
    F("license_issue_date", "Issue Date", type="date", section="Licence"),
    F("license_expiry_date", "Expiry Date", type="date", list=True, section="Licence"),
    F("hazardous_endorsement", "Hazardous Endorsement", type="bool", section="Licence"),
    F("medical_expiry_date", "Medical Expiry", type="date", section="Licence"),
    F("branch_id", "Branch", type="fk", fk="branches", list=True, filter=True, section="Engagement"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", section="Engagement"),
    F("engagement_type", "Engagement", type="lookup", lookup="DRIVER_ENGAGEMENT", section="Engagement"),
    F("status", "Status", type="lookup", lookup="DRIVER_STATUS", default="ACTIVE", list=True, filter=True, section="Engagement"),
    remarks()], code_field="driver_code", label_fields=("driver_code", "name"), branch_field="branch_id",
    documents=True, group="Drivers", status_field="status", before_save=lambda ctx, d, data, new: _driver_check(d)))

# ═════════════════════════════ COMPLIANCE ═════════════════════════════
RENEW_FIELDS = [
    F("certificate_number", "Certificate / Policy No.", maxlen=80), F("issue_date", "Issue Date", type="date"),
    F("start_date", "Start Date", type="date"), F("expiry_date", "Expiry Date", type="date", required=True),
    F("renewal_date", "Renewal Date", type="date"), F("amount", "Amount", type="money"),
    F("tax_amount", "Tax", type="money"), F("provider_id", "Provider", type="fk", fk="providers"),
    F("authority", "Authority", maxlen=150), F("document_number", "Document No.", maxlen=80),
    F("payment_status", "Payment", type="select", choices=PAY_STATUS), F("remarks", "Remarks", type="textarea")]

register(MasterSpec("vehicle_renewals", C.VehicleRenewal, "Renewals (Tax, Permit, Fitness, PUCC, PESO …)", "compliance",
                    "ti-certificate", [
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, readonly_on_edit=True, section="Subject"),
    F("driver_id", "Driver", type="fk", fk="drivers", filter=True, readonly_on_edit=True, section="Subject"),
    F("renewal_type_id", "Renewal Type", type="fk", fk="renewal_types", required=True, list=True, filter=True,
      readonly_on_edit=True, section="Subject"),
    F("assignment_id", "Renewal Slot", type="fk", fk="renewal_assignments", depends_on="vehicle_id", readonly_on_edit=True,
      section="Subject", hint="blank = PRIMARY slot"),
    F("reference_label", "New Slot Label", virtual=True, section="Subject", hint="e.g. PESO - TANK 2"),
    F("certificate_number", "Certificate No.", maxlen=80, list=True, search=True, section="Certificate"),
    F("issue_date", "Issue Date", type="date", section="Certificate"),
    F("start_date", "Start Date", type="date", section="Certificate"),
    F("expiry_date", "Expiry Date", type="date", required=True, list=True, section="Certificate"),
    F("renewal_date", "Renewal Date", type="date", section="Certificate"),
    F("provider_id", "Provider", type="fk", fk="providers", section="Certificate"),
    F("authority", "Authority", maxlen=150, section="Certificate"),
    F("document_number", "Document No.", maxlen=80, search=True, section="Certificate"),
    F("amount", "Amount", type="money", section="Payment"), F("tax_amount", "Tax", type="money", section="Payment"),
    F("total_amount", "Total", type="money", readonly=True, list=True, section="Payment"),
    F("payment_status", "Payment", type="select", choices=PAY_STATUS, default="PENDING", list=True, filter=True, section="Payment"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", section="Payment"),
    F("status", "Status", type="select", choices=RENEWAL_STATUS, readonly=True, list=True, filter=True, section="Payment"),
    F("is_current", "Current", type="bool", readonly=True, filter=True, section="Payment"), remarks()],
    actions=[Action("renew", "Renew", "ti-refresh", "compliance.renew", renewals.renew, RENEW_FIELDS,
                    visible_when={"is_current": [True]}, style="act"),
             Action("paid", "Mark Paid", "ti-cash", "compliance.edit", renewals.mark_paid,
                    visible_when={"payment_status": ["PENDING"]}),
             Action("cancel", "Cancel", "ti-ban", "compliance.edit", renewals.cancel_renewal,
                    [F("reason", "Reason", type="textarea", required=True)], style="del", reason_required=True)],
    code_field="certificate_number", title_field="certificate_number", label_fields=("certificate_number", "expiry_date"),
    before_save=renewals.renewal_before_save, after_save=renewals.renewal_after_save,
    serialize_extra=renewals.renewal_extra, documents=True, group="Compliance", status_field="status",
    date_field="expiry_date", default_sort="expiry_date", default_dir="asc", can_delete=False,
    branch_via_vehicle="vehicle_id", fixed_filters=None))

def _renewal_query(ctx, stmt, params):
    if params.get("category") or params.get("applies"):
        stmt = stmt.join(C.RenewalType, C.RenewalType.id == C.VehicleRenewal.renewal_type_id)
        if params.get("category"):
            stmt = stmt.where(C.RenewalType.category.in_(params["category"].split(",")))
        if params.get("applies"):
            stmt = stmt.where(C.RenewalType.applies_to == params["applies"])
    return stmt


_R["vehicle_renewals"].list_query = _renewal_query

register(MasterSpec("renewal_assignments", C.VehicleRenewalAssignment, "Renewal Slots per Vehicle", "compliance",
                    "ti-list-check", [
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True),
    F("driver_id", "Driver", type="fk", fk="drivers", filter=True),
    F("renewal_type_id", "Renewal Type", type="fk", fk="renewal_types", required=True, list=True, filter=True),
    F("renewal_rule_id", "Rule", type="fk", fk="renewal_rules", readonly=True, list=True),
    F("reference_label", "Reference Label", required=True, upper=True, maxlen=100, default="PRIMARY", list=True, search=True),
    F("is_applicable", "Applicable", type="bool", default=True, list=True, filter=True),
    F("reminder_days", "Reminder Days (override)", maxlen=100), F("remarks", "Remarks", maxlen=255)],
    actions=[Action("toggle_applicable", "Toggle Applicable", "ti-switch", "compliance.edit", renewals.mark_not_applicable,
                    [F("reason", "Reason", type="textarea", required=True)], reason_required=True)],
    code_field="reference_label", label_fields=("reference_label", "id"), group="Compliance",
    branch_via_vehicle="vehicle_id"))

register(MasterSpec("renewal_history", C.RenewalHistory, "Renewal History", "compliance", "ti-history", [
    F("renewal_id", "Renewal", type="int", list=True, filter=True, readonly=True),
    F("action", "Action", list=True, filter=True, readonly=True), F("old_status", "Old", list=True, readonly=True),
    F("new_status", "New", list=True, readonly=True), F("remarks", "Remarks", list=True, readonly=True),
    F("changed_at", "When", type="datetime", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Compliance",
    date_field="changed_at"))

INS_RENEW = [F("policy_number", "New Policy No.", required=True, maxlen=80),
             F("provider_id", "Insurer (blank = same)", type="fk", fk="providers", fk_filter={"provider_type": "INSURANCE"}),
             F("start_date", "Start", type="date", required=True), F("expiry_date", "Expiry", type="date", required=True),
             F("insured_amount", "Sum Insured / IDV", type="money"), F("premium", "Premium", type="money"),
             F("tax_amount", "Tax", type="money"), F("payment_status", "Payment", type="select", choices=PAY_STATUS),
             F("payment_reference", "Payment Ref.", maxlen=80), F("remarks", "Remarks", type="textarea")]
register(MasterSpec("insurance_policies", C.InsurancePolicy, "Insurance Policies", "compliance", "ti-shield-check", [
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, section="Policy"),
    F("driver_id", "Driver (driver policies)", type="fk", fk="drivers", filter=True, section="Policy"),
    F("provider_id", "Insurer", type="fk", fk="providers", required=True, list=True, filter=True,
      fk_filter={"provider_type": "INSURANCE"}, section="Policy"),
    F("policy_type", "Policy Type", type="lookup", lookup="INSURANCE_POLICY_TYPE", required=True, list=True, filter=True,
      section="Policy"),
    F("policy_number", "Policy No.", required=True, maxlen=80, list=True, search=True, section="Policy"),
    F("insured_amount", "Sum Insured / IDV", type="money", section="Policy"),
    F("start_date", "Start Date", type="date", required=True, list=True, section="Period"),
    F("expiry_date", "Expiry Date", type="date", required=True, list=True, section="Period"),
    F("renewal_status", "Renewal Status", type="select", choices=RENEWAL_STATUS, readonly=True, list=True, filter=True,
      section="Period"),
    F("is_current", "Current", type="bool", readonly=True, filter=True, section="Period"),
    F("premium", "Premium", type="money", section="Premium"), F("tax_amount", "Tax", type="money", section="Premium"),
    F("total_premium", "Total Premium", type="money", readonly=True, list=True, section="Premium"),
    F("payment_mode", "Payment Mode", type="lookup", lookup="PAYMENT_MODE", section="Premium"),
    F("payment_reference", "Payment Ref.", maxlen=80, section="Premium"),
    F("payment_date", "Payment Date", type="date", section="Premium"),
    F("payment_status", "Payment", type="select", choices=PAY_STATUS, default="PENDING", list=True, section="Premium"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", section="Premium"), remarks()],
    actions=[Action("renew", "Renew Policy", "ti-refresh", "compliance.renew", renewals.renew_policy, INS_RENEW,
                    visible_when={"is_current": [True]}, style="act")],
    code_field="policy_number", title_field="policy_number", label_fields=("policy_number",),
    before_save=renewals.insurance_before_save, after_save=renewals.insurance_after_save,
    serialize_extra=renewals.insurance_extra, documents=True, group="Compliance", status_field="renewal_status",
    date_field="expiry_date", default_sort="expiry_date", default_dir="asc", can_delete=False,
    branch_via_vehicle="vehicle_id"))

register(MasterSpec("insurance_history", C.InsuranceHistory, "Insurance History", "compliance", "ti-history", [
    F("policy_id", "Policy", type="fk", fk="insurance_policies", list=True, filter=True, readonly=True),
    F("action", "Action", list=True, readonly=True), F("old_status", "Old", list=True, readonly=True),
    F("new_status", "New", list=True, readonly=True), F("changed_at", "When", type="datetime", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Compliance"))

# ═════════════════════════════ CONTRACTS & INCOME ═════════════════════════════
register(MasterSpec("contracts", FI.Contract, "Contracts", "contract", "ti-file-certificate", [
    F("customer_id", "Customer", type="fk", fk="customers", required=True, list=True, filter=True, section="Contract"),
    F("contract_number", "Contract No.", required=True, upper=True, maxlen=50, list=True, search=True, section="Contract"),
    F("contract_date", "Contract Date", type="date", section="Contract"),
    F("start_date", "Start Date", type="date", required=True, list=True, section="Contract"),
    F("end_date", "End Date", type="date", list=True, section="Contract"),
    F("contract_type", "Contract Type", type="lookup", lookup="CONTRACT_TYPE", list=True, section="Contract"),
    F("billing_method", "Billing Method", type="lookup", lookup="BILLING_METHOD", section="Billing"),
    F("rate", "Rate", type="money", section="Billing"), F("rate_unit_id", "Rate Unit", type="fk", fk="units", section="Billing"),
    F("contract_value", "Contract Value", type="money", list=True, section="Billing"),
    F("payment_terms_days", "Payment Terms (days)", type="int", section="Billing"),
    F("cost_center_id", "Contract Cost Center", type="fk", fk="cost_centers", section="Billing"),
    F("branch_id", "Branch", type="fk", fk="branches", filter=True, section="Billing"),
    F("status", "Status", type="lookup", lookup="CONTRACT_STATUS", default="ACTIVE", list=True, filter=True, section="Billing"),
    F("invoice_details", "Invoice Details", type="textarea", span=3, section="Remarks"), remarks()],
    children=[Child("vehicles", "Vehicle / Cost Center Allocation", FI.ContractVehicleAllocation, "contract_id", [
        F("vehicle_id", "Vehicle", type="fk", fk="vehicles"), F("cost_center_id", "Cost Center", type="fk", fk="cost_centers"),
        F("allocation_percent", "Allocation %", type="decimal", min=0, max=100), F("fixed_amount", "Fixed Amount", type="money"),
        F("effective_from", "From", type="date"), F("effective_to", "To", type="date"), F("remarks", "Remarks")],
        prepare=cc_from_vehicle("start_date"))],
    code_field="contract_number", title_field="contract_number", label_fields=("contract_number",),
    before_save=contracts.contract_before_save, after_save=contracts.contract_after_save, documents=True,
    group="Contracts & Income", status_field="status", branch_field="branch_id"))

register(MasterSpec("invoices", FI.Invoice, "Invoices / Credit Notes / Advances", "contract", "ti-file-invoice", [
    F("invoice_number", "Invoice No.", required=True, upper=True, maxlen=50, list=True, search=True, section="Invoice"),
    F("invoice_type", "Type", type="select", choices=["INVOICE", "PARTIAL", "ADVANCE", "CREDIT_NOTE", "DEBIT_NOTE"],
      default="INVOICE", required=True, list=True, filter=True, section="Invoice"),
    F("customer_id", "Customer", type="fk", fk="customers", required=True, list=True, filter=True, section="Invoice"),
    F("contract_id", "Contract", type="fk", fk="contracts", depends_on="customer_id", list=True, section="Invoice"),
    F("original_invoice_id", "Original Invoice (credit note)", type="fk", fk="invoices", depends_on="customer_id",
      section="Invoice"),
    F("invoice_date", "Invoice Date", type="date", required=True, list=True, section="Dates"),
    F("due_date", "Due Date", type="date", list=True, section="Dates"),
    F("period_from", "Period From", type="date", section="Dates"), F("period_to", "Period To", type="date", section="Dates"),
    F("taxable_amount", "Taxable Amount", type="money", required=True, section="Amounts"),
    F("tax_amount", "GST", type="money", default=0, section="Amounts"),
    F("total_amount", "Total", type="money", readonly=True, list=True, section="Amounts"),
    F("received_amount", "Received", type="money", readonly=True, list=True, section="Amounts"),
    F("outstanding_amount", "Outstanding", type="money", readonly=True, list=True, section="Amounts"),
    F("status", "Status", type="select", choices=["OPEN", "PARTIALLY_PAID", "PAID", "OVERPAID", "CANCELLED", "APPLIED"],
      readonly=True, list=True, filter=True, section="Amounts"), remarks()],
    children=[Child("allocations", "Income Allocation (vehicle / cost center)", FI.InvoiceAllocation, "invoice_id", [
        F("vehicle_id", "Vehicle", type="fk", fk="vehicles"), F("cost_center_id", "Cost Center", type="fk", fk="cost_centers"),
        F("amount", "Amount", type="money", required=True, min=0.01), F("remarks", "Remarks")],
        prepare=cc_from_vehicle("invoice_date"))],
    actions=[Action("cancel", "Cancel Invoice", "ti-ban", "contract.edit", contracts.cancel_invoice,
                    [F("reason", "Reason", type="textarea", required=True)], style="del", reason_required=True,
                    visible_when={"status": ["OPEN"]})],
    code_field="invoice_number", title_field="invoice_number", label_fields=("invoice_number",),
    before_save=contracts.invoice_before_save, after_save=contracts.invoice_after_save,
    serialize_extra=contracts.invoice_extra, documents=True, group="Contracts & Income", status_field="status",
    date_field="invoice_date", can_delete=False))

# ═════════════════════════════ FINANCE ═════════════════════════════
register(MasterSpec("bank_transactions", FI.BankTransaction, "Bank Statement Transactions", "finance", "ti-receipt", [
    F("bank_account_id", "Bank Account", type="fk", fk="bank_accounts", required=True, list=True, filter=True,
      readonly_on_edit=True),
    F("txn_date", "Txn Date", type="date", required=True, list=True), F("value_date", "Value Date", type="date"),
    F("narration", "Narration", maxlen=500, span=2, list=True, search=True),
    F("credit", "Credit", type="money", list=True), F("debit", "Debit", type="money", list=True),
    F("reference_number", "Reference", maxlen=80, search=True), F("utr", "UTR", maxlen=40, search=True, list=True),
    F("cheque_number", "Cheque No.", maxlen=20), F("balance", "Balance", type="money"),
    F("counterparty", "Counterparty", maxlen=200, search=True),
    F("direction", "Dir", readonly=True, list=True, filter=True, type="select", choices=["CR", "DR"]),
    F("classification", "Classification", readonly=True, list=True, filter=True),
    F("recon_status", "Recon Status", type="select", choices=RECON_STATUS, readonly=True, list=True, filter=True),
    F("matched_amount", "Matched", type="money", readonly=True), F("unmatched_amount", "Unmatched", type="money",
                                                                   readonly=True, list=True),
    F("source_type", "Source", type="select", choices=SOURCE_TYPES, readonly=True, filter=True),
    F("source_file", "Source File", readonly=True), F("source_row", "Source Row", type="int", readonly=True),
    F("import_batch_id", "Import Batch", type="int", readonly=True, filter=True), remarks()],
    code_field="utr", title_field="narration", label_fields=("txn_date", "amount", "narration"),
    before_save=bank.bank_before_save, after_save=bank.bank_after_save, date_field="txn_date",
    default_sort="txn_date", documents=True, group="Finance", status_field="recon_status", can_delete=False))

register(MasterSpec("financial_links", FI.FinancialTransactionLink, "Financial Transaction Links", "finance", "ti-link", [
    F("source_transaction_type", "Source", list=True, filter=True, readonly=True),
    F("source_transaction_id", "Source ID", type="int", list=True, filter=True, readonly=True),
    F("target_transaction_type", "Target", list=True, filter=True, readonly=True),
    F("target_transaction_id", "Target ID", type="int", list=True, filter=True, readonly=True),
    F("linked_amount", "Amount", type="money", list=True, readonly=True),
    F("link_type", "Link Type", type="select", choices=LINK_TYPES, list=True, filter=True, readonly=True),
    F("match_status", "Status", list=True, filter=True, readonly=True),
    F("matching_method", "Method", list=True, filter=True, readonly=True),
    F("match_score", "Score", type="int", list=True, readonly=True),
    F("matched_at", "Matched At", type="datetime", list=True, readonly=True),
    F("approved_at", "Approved At", type="datetime", readonly=True), F("remarks", "Remarks", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Finance"))

register(MasterSpec("bank_allocations", FI.BankTransactionAllocation, "Bank Cost-Center Allocations", "finance", "ti-chart-pie", [
    F("bank_transaction_id", "Bank Txn", type="int", list=True, filter=True, readonly=True),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", list=True, filter=True, readonly=True),
    F("expense_type_id", "Expense Type", type="fk", fk="expense_types", list=True, readonly=True),
    F("credit_type_id", "Credit Type", type="fk", fk="credit_types", list=True, readonly=True),
    F("vendor_id", "Vendor", type="fk", fk="vendors", list=True, readonly=True),
    F("amount", "Amount", type="money", list=True, readonly=True),
    F("status", "Status", list=True, filter=True, readonly=True), F("remarks", "Remarks", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Finance"))

register(MasterSpec("recon_history", FI.ReconciliationHistory, "Reconciliation History", "finance", "ti-history", [
    F("bank_transaction_id", "Bank Txn", type="int", list=True, filter=True, readonly=True),
    F("action", "Action", list=True, filter=True, readonly=True), F("old_status", "Old", list=True, readonly=True),
    F("new_status", "New", list=True, readonly=True), F("amount", "Amount", type="money", list=True, readonly=True),
    F("remarks", "Remarks", list=True, readonly=True), F("performed_at", "When", type="datetime", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Finance",
    date_field="performed_at", default_sort="performed_at"))

register(MasterSpec("expenses", FI.ExpenseTransaction, "Vendor Invoices / Operational Expenses", "finance", "ti-receipt-2", [
    F("document_number", "Document No.", required=True, upper=True, maxlen=50, list=True, search=True, section="Document"),
    F("expense_date", "Date", type="date", required=True, list=True, section="Document"),
    F("expense_type_id", "Expense Type", type="fk", fk="expense_types", required=True, list=True, filter=True, section="Document"),
    F("vendor_id", "Vendor", type="fk", fk="vendors", list=True, filter=True, section="Document"),
    F("invoice_number", "Vendor Invoice No.", maxlen=50, search=True, section="Document"),
    F("invoice_date", "Invoice Date", type="date", section="Document"),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, section="Allocation"),
    F("driver_id", "Driver", type="fk", fk="drivers", section="Allocation"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", list=True, filter=True, section="Allocation"),
    F("amount", "Amount (ex tax)", type="money", required=True, section="Amounts"),
    F("tax_amount", "Tax", type="money", default=0, section="Amounts"),
    F("total_amount", "Total", type="money", readonly=True, list=True, section="Amounts"),
    F("status", "Status", type="select", choices=["POSTED", "CANCELLED"], default="POSTED", list=True, section="Amounts"),
    F("description", "Description", type="textarea", span=3, section="Remarks")],
    children=[Child("allocations", "Split across Cost Centers (optional)", FI.ExpenseAllocation, "expense_id", [
        F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", hint="or vehicle"),
        F("vehicle_id", "Vehicle", type="fk", fk="vehicles"), F("amount", "Amount", type="money", required=True),
        F("remarks", "Remarks")], prepare=cc_from_vehicle("expense_date"))],
    code_field="document_number", title_field="document_number", label_fields=("document_number", "total_amount"),
    before_save=contracts.expense_before_save, after_save=contracts.expense_after_save, date_field="expense_date",
    documents=True, group="Vendors", status_field="status", can_delete=False, branch_via_vehicle="vehicle_id"))

# ═════════════════════════════ IMPORTS ═════════════════════════════
register(MasterSpec("import_templates", IM.StatementImportTemplate, "Import Templates (Template Builder)", "import",
                    "ti-template", [
    F("provider_id", "Provider", type="fk", fk="providers", required=True, list=True, filter=True, section="Template"),
    F("template_name", "Template Name", required=True, maxlen=100, list=True, search=True, section="Template"),
    F("statement_type", "Statement Type", type="select", choices=STATEMENT_TYPES, required=True, list=True, filter=True,
      section="Template"),
    F("version", "Version", type="int", default=1, list=True, section="Template"),
    F("effective_from", "Effective From", type="date", section="Template"),
    F("effective_to", "Effective To", type="date", section="Template"),
    F("file_format", "File Format", type="select", choices=["XLSX", "CSV"], default="XLSX", section="Layout"),
    F("sheet_name", "Sheet Name", maxlen=100, section="Layout", hint="blank = first sheet"),
    F("header_row", "Header Row", type="int", default=1, min=1, section="Layout"),
    F("data_start_row", "Data Starts at Row", type="int", default=2, min=1, section="Layout"),
    F("stop_at_blank_rows", "Stop after N blank rows", type="int", default=3, section="Layout"),
    F("skip_footer_keywords", "Skip rows starting with", maxlen=255, section="Layout", hint="e.g. Closing Balance,Total"),
    F("date_format", "Date Format", maxlen=30, section="Layout", hint="e.g. %d/%m/%Y, %d-%b-%Y"),
    F("datetime_format", "Date-time Format", maxlen=40, section="Layout"),
    F("amount_mode", "Amount Columns", type="select", choices=["SEPARATE", "SIGNED", "WITH_TYPE"], default="SEPARATE",
      section="Layout"),
    F("duplicate_key_fields", "Duplicate Key Fields", maxlen=255, section="Layout", hint="optional, e.g. txn_date,amount,reference_number"),
    F("description", "Notes", type="textarea", span=3, section="Remarks")],
    children=[Child("columns", "Column Mapping", IM.StatementTemplateColumn, "template_id", [
        F("source_column", "Column (A/B/…)", upper=True, maxlen=10), F("source_header", "Header Text", maxlen=150),
        F("target_field", "Target Field", required=True, maxlen=60),
        F("data_type", "Type", type="select", choices=["TEXT", "DATE", "DATETIME", "TIME", "DECIMAL", "INTEGER"]),
        F("is_required", "Req.", type="bool"), F("transformation", "Transformation", maxlen=500),
        F("default_value", "Default", maxlen=150), F("lookup_rule", "Lookup", type="select", choices=sorted(import_engine.LOOKUPS)),
        F("validation_rule", "Validation", maxlen=255), F("display_order", "Order", type="int", default=0)],
        order_by="display_order", min_rows=1)],
    code_field="template_name", title_field="template_name", label_fields=("template_name", "version"),
    after_save=import_engine.template_after_save, group="Imports", documents=True))

register(MasterSpec("import_batches", IM.StatementImportBatch, "Import Batches / History", "import", "ti-files", [
    F("provider_id", "Provider", type="fk", fk="providers", list=True, filter=True, readonly=True),
    F("template_id", "Template", type="fk", fk="import_templates", list=True, filter=True, readonly=True),
    F("statement_type", "Type", list=True, filter=True, readonly=True),
    F("bank_account_id", "Bank Account", type="fk", fk="bank_accounts", readonly=True),
    F("file_name", "File", list=True, search=True, readonly=True), F("sheet_name", "Sheet", readonly=True),
    F("imported_at", "Imported At", type="datetime", list=True, readonly=True),
    F("total_rows", "Rows", type="int", list=True, readonly=True),
    F("successful_rows", "Imported", type="int", list=True, readonly=True),
    F("duplicate_rows", "Duplicates", type="int", list=True, readonly=True),
    F("error_rows", "Errors", type="int", list=True, readonly=True),
    F("warning_rows", "Warnings", type="int", readonly=True), F("unmatched_rows", "Unmatched", type="int", list=True, readonly=True),
    F("status", "Status", list=True, filter=True, readonly=True), F("file_hash", "File Hash", readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field="file_name", title_field="file_name",
    label_fields=("id", "file_name"), group="Imports", date_field="created_at", default_sort="id"))


def _resolve_error(ctx, e: IM.StatementImportError, data):
    e.resolved, e.resolved_by, e.resolved_at = True, ctx.user.id, now()
    e.resolution_notes = data.get("resolution_notes")
    audit(ctx.db, ctx.user, "RESOLVE", "statement_import_errors", e.id, new={"notes": e.resolution_notes})
    return {"message": "Marked resolved"}


register(MasterSpec("import_errors", IM.StatementImportError, "Import Errors", "import", "ti-alert-triangle", [
    F("batch_id", "Batch", type="int", list=True, filter=True, readonly=True),
    F("source_row", "Row", type="int", list=True, readonly=True), F("source_column", "Column", list=True, readonly=True),
    F("target_field", "Field", list=True, readonly=True), F("original_value", "Original Value", list=True, readonly=True),
    F("error_type", "Type", list=True, filter=True, readonly=True),
    F("error_message", "Error", list=True, search=True, readonly=True),
    F("suggested_correction", "Suggestion", list=True, readonly=True),
    F("severity", "Severity", list=True, filter=True, readonly=True),
    F("resolved", "Resolved", type="bool", list=True, filter=True, readonly=True),
    F("resolution_notes", "Resolution Notes", readonly=True)],
    actions=[Action("resolve", "Mark Resolved", "ti-check", "import.edit", _resolve_error,
                    [F("resolution_notes", "Resolution Notes", type="textarea", required=True)],
                    visible_when={"resolved": [False]})],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Imports",
    default_sort="id"))

# ═════════════════════════════ FUEL ═════════════════════════════
register(MasterSpec("fuel_stations", OP.FuelStation, "Fuel Stations", "fuel", "ti-building-factory-2", [
    F("provider_id", "Provider", type="fk", fk="providers", list=True, filter=True, fk_filter={"provider_type": "FUEL"}),
    F("station_code", "Station Code", required=True, upper=True, maxlen=40, list=True, search=True),
    name(200, "Station Name"), F("city", "City", maxlen=100, list=True),
    F("state_id", "State", type="fk", fk="states", list=True), F("district_id", "District", type="fk", fk="districts",
                                                                depends_on="state_id"),
    F("pincode", "Pincode", maxlen=6), F("latitude", "Latitude", type="decimal"), F("longitude", "Longitude", type="decimal"),
    F("contact", "Contact", maxlen=100), F("address", "Address", type="textarea", span=3)],
    code_field="station_code", label_fields=("station_code", "name"), group="Fuel"))

register(MasterSpec("fuel_cards", OP.FuelCard, "Fuel / Fleet Cards", "fuel", "ti-credit-card", [
    F("provider_id", "Provider", type="fk", fk="providers", required=True, list=True, filter=True),
    F("card_number", "Card Number", required=True, maxlen=40, list=True, search=True),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True),
    F("effective_from", "From", type="date"), F("effective_to", "To", type="date"), F("remarks", "Remarks", maxlen=255)],
    code_field="card_number", label_fields=("card_number",), group="Fuel"))

FUEL_OVR = [F("override", "Override validation (authorised)", type="bool", virtual=True, section="Override"),
            F("override_reason", "Override Reason", type="textarea", virtual=True, span=2, section="Override")]
register(MasterSpec("fuel_transactions", OP.FuelTransaction, "Fuel Transactions", "fuel", "ti-gas-station", [
    F("provider_id", "Provider", type="fk", fk="providers", list=True, filter=True, fk_filter={"provider_type": "FUEL"},
      section="Transaction"),
    F("provider_transaction_id", "Provider Txn ID", maxlen=80, search=True, section="Transaction"),
    F("txn_datetime", "Date & Time", type="datetime", required=True, list=True, section="Transaction"),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, section="Transaction"),
    F("vehicle_number_raw", "Vehicle No. (as received)", readonly=True, search=True, section="Transaction"),
    F("fuel_station_id", "Fuel Station", type="fk", fk="fuel_stations", section="Transaction"),
    F("card_number", "Card", maxlen=40, search=True, section="Transaction"),
    F("fuel_type_id", "Fuel Type", type="fk", fk="fuel_types", required=True, list=True, filter=True, section="Quantity"),
    F("quantity", "Quantity", type="decimal", required=True, min=0, list=True, section="Quantity"),
    F("unit_id", "Unit", type="fk", fk="units", section="Quantity"),
    F("rate", "Rate", type="decimal", section="Quantity"), F("amount", "Amount", type="money", section="Quantity"),
    F("tax_amount", "Tax", type="money", section="Quantity"), F("discount_amount", "Discount", type="money", section="Quantity"),
    F("total_amount", "Total", type="money", list=True, section="Quantity"),
    F("invoice_number", "Invoice", maxlen=50, search=True, section="Quantity"),
    F("odometer", "Odometer", type="decimal", list=True, section="Quantity"),
    F("efficiency", "Efficiency", type="decimal", readonly=True, list=True, section="Validation"),
    F("efficiency_flag", "Efficiency Flag", readonly=True, list=True, filter=True, section="Validation"),
    F("status", "Status", type="select", choices=FUEL_STATUS, readonly=True, list=True, filter=True, section="Validation"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", readonly=True, section="Validation"),
    F("source_type", "Source", type="select", choices=SOURCE_TYPES, readonly=True, filter=True, list=True, section="Validation"),
    F("source_file", "Source File", readonly=True, section="Validation"),
    F("source_row", "Source Row", type="int", readonly=True, section="Validation"),
    F("import_batch_id", "Batch", type="int", readonly=True, filter=True, section="Validation"),
    *FUEL_OVR, remarks()],
    actions=[Action("resolve", "Resolve / Review", "ti-user-check", "fuel.edit", operations.fuel_resolve, [
        F("vehicle_id", "Vehicle", type="fk", fk="vehicles"), F("fuel_type_id", "Fuel Type", type="fk", fk="fuel_types"),
        F("create_mapping", "Remember vehicle mapping for future imports", type="bool"),
        F("accept", "Accept flagged transaction (override)", type="bool"),
        F("reason", "Reason", type="textarea", required=True)],
        visible_when={"status": ["VEHICLE_UNMATCHED", "FLAGGED", "IMPORTED"]}, reason_required=True)],
    code_field="provider_transaction_id", title_field="provider_transaction_id",
    label_fields=("txn_date", "total_amount"), before_save=operations.fuel_before_save,
    after_save=operations.fuel_after_save, date_field="txn_date", default_sort="txn_datetime", group="Fuel",
    status_field="status", documents=True, can_delete=False, branch_via_vehicle="vehicle_id"))

# ═════════════════════════════ TOLL ═════════════════════════════
register(MasterSpec("toll_plazas", OP.TollPlaza, "Toll Plazas", "toll", "ti-road", [
    F("plaza_code", "Plaza Code", required=True, upper=True, maxlen=40, list=True, search=True, section="Plaza"),
    F("external_plaza_id", "Toll ID (source)", maxlen=40, list=True, search=True, section="Plaza",
      hint="ID given by NHAI / FASTag / OSM"),
    F("name", "Toll Plaza Name", required=True, maxlen=200, list=True, search=True, section="Plaza"),
    F("place", "Place", required=True, maxlen=150, list=True, search=True, filter=True, section="Location"),
    F("state_id", "State", type="fk", fk="states", required=True, list=True, filter=True, section="Location"),
    F("district_id", "District", type="fk", fk="districts", depends_on="state_id", section="Location"),
    F("highway", "Highway", maxlen=50, list=True, section="Location"), F("road", "Road", maxlen=150, section="Location"),
    F("latitude", "Latitude", type="decimal", section="Location"), F("longitude", "Longitude", type="decimal", section="Location"),
    F("operator", "Operator", maxlen=150, section="Source"), F("provider_id", "Provider", type="fk", fk="providers", section="Source"),
    F("api_source", "Fetched From", maxlen=60, list=True, filter=True, readonly=True, section="Source"),
    F("state_name", "State (as in source)", maxlen=100, readonly=True, section="Source"),
    F("api_last_synced_at", "Last Fetched", type="datetime", readonly=True, list=True, section="Source")],
    code_field="plaza_code", label_fields=("plaza_code", "name"), group="Toll",
    description="Use “Fetch from Internet” to add / update plazas from OpenStreetMap, data.gov.in or a FASTag API. "
                "Toll ID, name, place and state are compulsory."))

register(MasterSpec("toll_plaza_sync_runs", OP.TollPlazaSyncRun, "Toll Plaza Internet Sync History", "toll", "ti-cloud-download", [
    F("started_at", "Started", type="datetime", list=True, readonly=True),
    F("integration_id", "Source", type="fk", fk="api_integrations", list=True, filter=True, readonly=True),
    F("source", "Adapter", list=True, filter=True, readonly=True), F("states", "States", list=True, readonly=True),
    F("dry_run", "Dry Run", type="bool", list=True, readonly=True),
    F("status", "Status", type="select", choices=["QUEUED", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"], list=True,
      filter=True, readonly=True),
    F("states_done", "States Done", type="int", readonly=True), F("states_total", "States Total", type="int", readonly=True),
    F("fetched", "Fetched", type="int", list=True, readonly=True), F("created", "Created", type="int", list=True, readonly=True),
    F("updated", "Updated", type="int", list=True, readonly=True), F("unchanged", "Unchanged", type="int", list=True, readonly=True),
    F("skipped", "Skipped", type="int", list=True, readonly=True),
    F("finished_at", "Finished", type="datetime", list=True, readonly=True),
    F("triggered_by", "By", type="fk", fk="users", readonly=True),
    F("error_message", "Errors", type="textarea", readonly=True, span=3),
    F("skipped_samples", "Skipped Records (reasons)", type="json", readonly=True, span=3)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("source", "started_at"),
    group="Toll", default_sort="started_at"))

register(MasterSpec("toll_vehicle_mappings", OP.TollVehicleMapping, "Toll Vehicle Mappings", "toll", "ti-arrows-left-right", [
    F("provider_id", "Provider", type="fk", fk="providers", required=True, list=True, filter=True),
    F("external_vehicle_number", "External Vehicle No.", upper=True, maxlen=30, list=True, search=True),
    F("external_vehicle_id", "External Vehicle ID", maxlen=60, list=True, search=True),
    F("fastag_id", "FASTag ID", maxlen=40, list=True, search=True),
    F("vehicle_id", "Internal Vehicle", type="fk", fk="vehicles", required=True, list=True, filter=True),
    F("effective_from", "From", type="date", list=True), F("effective_to", "To", type="date", list=True)],
    code_field="external_vehicle_number", label_fields=("external_vehicle_number", "fastag_id"), group="Toll"))

register(MasterSpec("toll_transactions", OP.TollTransaction, "Toll Transactions", "toll", "ti-receipt-tax", [
    F("provider_id", "Provider", type="fk", fk="providers", required=True, list=True, filter=True,
      fk_filter={"provider_type": "TOLL"}, section="Transaction", readonly_on_edit=True),
    F("transaction_id", "Transaction ID", maxlen=80, list=True, search=True, section="Transaction", readonly_on_edit=True,
      hint="blank = auto for manual entry"),
    F("txn_date", "Date", type="date", required=True, list=True, section="Transaction"),
    F("txn_time", "Time", type="time", section="Transaction"),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, section="Transaction"),
    F("registration_raw", "Registration (as received)", upper=True, maxlen=30, search=True, section="Transaction"),
    F("fastag_id", "FASTag", maxlen=40, search=True, section="Transaction"),
    F("toll_plaza_id", "Toll Plaza", type="fk", fk="toll_plazas", list=True, filter=True, section="Plaza"),
    F("plaza_external_id_raw", "Plaza ID (raw)", maxlen=40, section="Plaza"),
    F("plaza_code_raw", "Plaza Code (raw)", maxlen=40, section="Plaza"),
    F("plaza_name_raw", "Plaza Name (raw)", maxlen=200, search=True, section="Plaza"),
    F("amount", "Amount", type="money", required=True, list=True, section="Plaza"),
    F("txn_kind", "Kind", type="select", choices=["DEBIT", "REFUND", "RECHARGE"], default="DEBIT", list=True, section="Plaza"),
    F("direction", "Direction", type="lookup", lookup="TOLL_DIRECTION", section="Plaza"), F("lane", "Lane", maxlen=20, section="Plaza"),
    F("status", "Status", type="select", choices=TOLL_STATUS, readonly=True, list=True, filter=True, section="Review"),
    F("vehicle_match_status", "Vehicle Match", readonly=True, filter=True, section="Review"),
    F("plaza_match_status", "Plaza Match", readonly=True, filter=True, section="Review"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", readonly=True, section="Review"),
    F("source_type", "Source", type="select", choices=SOURCE_TYPES, readonly=True, list=True, filter=True, section="Review"),
    F("source_file", "Source File", readonly=True, section="Review"),
    F("source_row", "Row", type="int", readonly=True, section="Review"),
    F("import_batch_id", "Batch", type="int", readonly=True, filter=True, section="Review"),
    F("review_notes", "Review Notes", readonly=True, section="Review"), remarks()],
    actions=[Action("resolve", "Resolve Vehicle / Plaza", "ti-user-check", "toll.edit", operations.toll_resolve, [
        F("vehicle_id", "Vehicle", type="fk", fk="vehicles"), F("toll_plaza_id", "Toll Plaza", type="fk", fk="toll_plazas"),
        F("create_mapping", "Remember mapping for future imports", type="bool"),
        F("reason", "Reason", type="textarea", required=True)], reason_required=True,
        visible_when={"status": ["VEHICLE_UNMATCHED", "PLAZA_UNMATCHED", "VEHICLE_MATCHED", "IMPORTED"]})],
    code_field="transaction_id", title_field="transaction_id", label_fields=("transaction_id", "amount"),
    before_save=operations.toll_before_save, date_field="txn_date", default_sort="txn_date", group="Toll",
    status_field="status", can_delete=False, branch_via_vehicle="vehicle_id"))

# ═════════════════════════════ MAINTENANCE ═════════════════════════════
register(MasterSpec("job_cards", OP.MaintenanceJobCard, "Maintenance Job Cards", "maintenance", "ti-tools", [
    F("job_card_number", "Job Card No.", required=True, upper=True, maxlen=40, list=True, search=True, section="Job"),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", required=True, list=True, filter=True, section="Job"),
    F("job_date", "Job Date", type="date", required=True, list=True, section="Job"),
    F("maintenance_type_id", "Type", type="fk", fk="maintenance_types", required=True, list=True, filter=True, section="Job"),
    F("odometer", "Odometer", type="decimal", section="Job"),
    F("vendor_id", "Vendor / Workshop", type="fk", fk="vendors", list=True, filter=True, section="Job"),
    F("workshop_location_id", "Own Workshop", type="fk", fk="locations", section="Job"),
    F("complaint", "Complaint", type="textarea", section="Work"), F("diagnosis", "Diagnosis", type="textarea", section="Work"),
    F("work_performed", "Work Performed", type="textarea", section="Work"),
    F("downtime_start", "Downtime Start", type="datetime", section="Downtime"),
    F("downtime_end", "Downtime End", type="datetime", section="Downtime"),
    F("downtime_hours", "Downtime (h)", type="decimal", readonly=True, section="Downtime"),
    F("completion_date", "Completed On", type="date", section="Downtime"),
    F("next_due_km", "Next Due (km)", type="decimal", section="Downtime"),
    F("next_due_date", "Next Due Date", type="date", section="Downtime"),
    F("parts_amount", "Parts", type="money", readonly=True, section="Amounts"),
    F("labour_amount", "Labour", type="money", readonly=True, section="Amounts"),
    F("other_amount", "Other / Consumables", type="money", default=0, section="Amounts"),
    F("tax_amount", "Tax", type="money", default=0, section="Amounts"),
    F("total_amount", "Total", type="money", readonly=True, list=True, section="Amounts"),
    F("invoice_number", "Invoice", maxlen=50, search=True, section="Amounts"),
    F("invoice_date", "Invoice Date", type="date", section="Amounts"),
    F("status", "Status", type="select", choices=["OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"], default="OPEN",
      list=True, filter=True, section="Amounts"),
    F("approval_status", "Approval", readonly=True, list=True, filter=True, section="Amounts"),
    F("cost_center_id", "Cost Center", type="fk", fk="cost_centers", readonly=True, section="Amounts"),
    F("override_reason", "Odometer Override Reason", type="textarea", virtual=True, section="Remarks"), remarks()],
    children=[Child("parts", "Parts & Consumables", OP.MaintenancePart, "job_card_id", [
        F("part_name", "Part", required=True, maxlen=150), F("part_number", "Part No.", maxlen=60),
        F("quantity", "Qty", type="decimal", default=1, min=0), F("unit_id", "Unit", type="fk", fk="units"),
        F("rate", "Rate", type="money"), F("amount", "Amount", type="money"), F("tax_amount", "Tax", type="money"),
        F("is_consumable", "Consumable", type="bool")]),
        Child("labour", "Labour", OP.MaintenanceLabour, "job_card_id", [
            F("description", "Description", required=True, maxlen=255), F("technician", "Technician", maxlen=100),
            F("hours", "Hours", type="decimal"), F("rate", "Rate", type="money"), F("amount", "Amount", type="money"),
            F("tax_amount", "Tax", type="money")])],
    actions=[Action("complete", "Complete", "ti-circle-check", "maintenance.edit", maintenance.complete,
                    [F("completion_date", "Completion Date", type="date"), F("work_performed", "Work Performed", type="textarea")],
                    visible_when={"status": ["OPEN", "IN_PROGRESS"]}, style="act"),
             Action("cancel", "Cancel", "ti-ban", "maintenance.edit", maintenance.cancel,
                    [F("reason", "Reason", type="textarea", required=True)], style="del", reason_required=True,
                    visible_when={"status": ["OPEN", "IN_PROGRESS"]})],
    code_field="job_card_number", title_field="job_card_number", label_fields=("job_card_number",),
    before_save=maintenance.before_save, after_save=maintenance.after_save, date_field="job_date",
    documents=True, group="Maintenance", status_field="status", can_delete=False, branch_via_vehicle="vehicle_id"))

# ═════════════════════════════ TYRES ═════════════════════════════
_FITTED = ["INSTALLED", "SHIFTED", "FITTED_AFTER_RETREAD"]
_STOCK = ["NEW", "IN_STOCK", "REMOVED", "IN_GODOWN", "RETREADED", "UNDER_INSPECTION"]
_ODO_OVR = F("reason", "Reason / Override Reason", type="textarea")
TYRE_ACTIONS = [
    Action("install", "Install", "ti-circle-plus", "tyre.move", tyres.install, [
        F("vehicle_id", "Vehicle", type="fk", fk="vehicles", required=True),
        F("position_id", "Position", type="fk", fk="tyre_positions", required=True),
        F("date", "Date", type="datetime", required=True), F("odometer", "Odometer", type="decimal", required=True),
        F("tread_depth", "Tread Depth (mm)", type="decimal"), F("performed_by", "Installer", maxlen=100),
        F("reference", "Reference", maxlen=80), _ODO_OVR], visible_when={"current_status": _STOCK}, style="act"),
    Action("shift", "Shift Position", "ti-arrows-exchange", "tyre.move", tyres.shift, [
        F("position_id", "New Position", type="fk", fk="tyre_positions", required=True),
        F("swap", "Swap with tyre in that position", type="bool"), F("date", "Date", type="datetime", required=True),
        F("odometer", "Odometer", type="decimal", required=True), F("tread_depth", "Tread Depth", type="decimal"),
        F("performed_by", "Performed By", maxlen=100), _ODO_OVR], visible_when={"current_status": _FITTED}),
    Action("transfer", "Transfer to Vehicle", "ti-truck-loading", "tyre.move", tyres.transfer, [
        F("to_vehicle_id", "To Vehicle", type="fk", fk="vehicles", required=True),
        F("position_id", "To Position", type="fk", fk="tyre_positions", required=True),
        F("date", "Date", type="datetime", required=True),
        F("from_odometer", "From-vehicle Odometer", type="decimal", required=True),
        F("to_odometer", "To-vehicle Odometer", type="decimal", required=True),
        F("tread_depth", "Tread Depth", type="decimal"), F("reference", "Reference", maxlen=80), _ODO_OVR],
        visible_when={"current_status": _FITTED}),
    Action("remove", "Remove", "ti-circle-minus", "tyre.move", tyres.remove, [
        F("date", "Date", type="datetime", required=True), F("odometer", "Odometer", type="decimal", required=True),
        F("tread_depth", "Tread Depth", type="decimal"), F("to_location_id", "Destination", type="fk", fk="tyre_locations", required=True),
        F("new_status", "Status", type="select", choices=["REMOVED", "IN_GODOWN", "UNDER_INSPECTION", "DAMAGED"]),
        F("reference", "Reference", maxlen=80), _ODO_OVR], visible_when={"current_status": _FITTED}, style="deact"),
    Action("move", "Move Location", "ti-building-warehouse", "tyre.move", tyres.move_location, [
        F("to_location_id", "To Location", type="fk", fk="tyre_locations", required=True),
        F("new_status", "Status", type="select", choices=["IN_STOCK", "IN_GODOWN", "UNDER_INSPECTION", "DAMAGED", "REMOVED"]),
        F("date", "Date", type="date"), F("reason", "Reason", type="textarea")],
        visible_when={"current_status": _STOCK + ["DAMAGED"]}),
    Action("send_retread", "Send for Retreading", "ti-recycle", "tyre.move", tyres.send_retread, [
        F("vendor_id", "Retreader", type="fk", fk="vendors", required=True),
        F("to_location_id", "Location", type="fk", fk="tyre_locations"), F("date", "Sent Date", type="date", required=True),
        F("tread_condition", "Tread Condition", maxlen=100), F("tread_depth", "Tread Depth", type="decimal"),
        F("retread_type", "Retread Type", type="lookup", lookup="RETREAD_TYPE"), F("remarks", "Remarks", type="textarea")],
        visible_when={"current_status": _STOCK + ["DAMAGED"]}),
    Action("receive_retread", "Receive from Retreading", "ti-package-import", "tyre.move", tyres.receive_retread, [
        F("date", "Return Date", type="date", required=True), F("rejected", "Rejected by retreader", type="bool"),
        F("cost", "Cost", type="money"), F("gst_amount", "GST", type="money"), F("invoice_number", "Invoice", maxlen=50),
        F("new_tread_depth", "New Tread Depth", type="decimal"), F("new_pattern", "New Pattern", maxlen=60),
        F("retread_serial", "Retread Serial", maxlen=50), F("warranty_km", "Warranty KM", type="int"),
        F("warranty_months", "Warranty Months", type="int"),
        F("to_location_id", "Receive Into", type="fk", fk="tyre_locations")],
        visible_when={"current_status": ["SENT_FOR_RETREADING"]}, style="act"),
    Action("inspect", "Inspection", "ti-zoom-check", "tyre.edit", tyres.inspect, [
        F("date", "Date", type="date", required=True), F("odometer", "Odometer", type="decimal"),
        F("tread_depth", "Tread Depth", type="decimal"), F("pressure_psi", "Pressure (psi)", type="decimal"),
        F("condition", "Condition", type="lookup", lookup="TYRE_CONDITION"), F("damage", "Damage", maxlen=255),
        F("recommended_action", "Recommended Action", maxlen=100), F("inspector", "Inspector", maxlen=100),
        F("remarks", "Remarks", type="textarea"), _ODO_OVR]),
    Action("maintain", "Tyre Maintenance", "ti-tool", "tyre.edit", tyres.maintain, [
        F("maintenance_type", "Type", type="lookup", lookup="TYRE_MAINTENANCE_TYPE", required=True),
        F("date", "Date", type="date", required=True), F("odometer", "Odometer", type="decimal"),
        F("vendor_id", "Vendor", type="fk", fk="vendors"), F("cost", "Cost", type="money"), F("gst_amount", "GST", type="money"),
        F("invoice_number", "Invoice", maxlen=50), F("remarks", "Remarks", type="textarea")]),
    Action("warranty", "Warranty Claim", "ti-shield", "tyre.edit", tyres.raise_warranty, [
        F("claim_number", "Claim No.", required=True, maxlen=50), F("date", "Claim Date", type="date", required=True),
        F("failure_date", "Failure Date", type="date"), F("failure_reason", "Failure Reason", maxlen=255, required=True),
        F("warranty_provider_id", "Warranty Provider", type="fk", fk="vendors"),
        F("claim_amount", "Claim Amount", type="money"), F("evidence", "Evidence / Notes", type="textarea")],
        visible_when={"current_status": _STOCK + ["DAMAGED"]}),
    Action("scrap", "Scrap", "ti-trash-x", "tyre.dispose", tyres.scrap, [
        F("date", "Scrap Date", type="date", required=True), F("reason", "Reason", type="textarea", required=True),
        F("scrap_value", "Scrap Value", type="money"), F("to_location_id", "Scrap Yard", type="fk", fk="tyre_locations")],
        visible_when={"current_status": _STOCK + ["DAMAGED", "WARRANTY"]}, style="del", reason_required=True),
    Action("dispose", "Sell / Mark Lost", "ti-coin", "tyre.dispose", tyres.dispose, [
        F("disposal", "Disposal", type="select", choices=["SOLD", "LOST"], required=True),
        F("date", "Date", type="date", required=True), F("sale_value", "Sale Value", type="money"),
        F("reference", "Reference", maxlen=80), F("reason", "Reason", type="textarea", required=True)],
        visible_when={"current_status": _STOCK + ["DAMAGED", "SCRAPPED"]}, style="del", reason_required=True),
    Action("correct", "Correction (audited)", "ti-pencil-exclamation", "tyre.correct", tyres.correct, [
        F("retread_count", "Retread Count", type="int", min=0), F("current_tread_depth", "Tread Depth", type="decimal"),
        F("total_km", "Total KM", type="decimal"), F("reason", "Reason", type="textarea", required=True)],
        reason_required=True, style="deact"),
]
register(MasterSpec("tyres", TY.Tyre, "Tyre Master", "tyre", "ti-circle-dashed", [
    F("serial_number", "Serial No.", required=True, upper=True, maxlen=50, list=True, search=True, section="Identity",
      readonly_on_edit=True),
    F("tyre_code", "Tyre Code", upper=True, maxlen=30, search=True, section="Identity"),
    F("brand", "Brand", required=True, upper=True, maxlen=60, list=True, filter=True, section="Identity"),
    F("model", "Model", upper=True, maxlen=60, list=True, section="Identity"),
    F("size", "Size", required=True, upper=True, maxlen=40, list=True, filter=True, section="Identity"),
    F("tyre_type", "Type", type="lookup", lookup="TYRE_TYPE", section="Identity"),
    F("pattern", "Pattern", maxlen=60, section="Specs"), F("ply_rating", "Ply Rating", maxlen=10, section="Specs"),
    F("load_index", "Load Index", maxlen=10, section="Specs"), F("speed_rating", "Speed Rating", maxlen=5, section="Specs"),
    F("original_tread_depth", "Original Tread (mm)", type="decimal", section="Specs"),
    F("manufacture_date", "Manufacture Date", type="date", section="Specs"),
    F("purchase_date", "Purchase Date", type="date", section="Purchase"),
    F("supplier_id", "Supplier", type="fk", fk="vendors", filter=True, section="Purchase"),
    F("invoice_number", "Invoice", maxlen=50, search=True, section="Purchase"),
    F("cost", "Cost", type="money", section="Purchase"), F("gst_amount", "GST", type="money", section="Purchase"),
    F("discount_amount", "Discount", type="money", section="Purchase"),
    F("total_cost", "Total Cost", type="money", readonly=True, section="Purchase"),
    F("warranty_km", "Warranty KM", type="int", section="Purchase"),
    F("warranty_months", "Warranty Months", type="int", section="Purchase"),
    F("warranty_expiry_date", "Warranty Expiry", type="date", section="Purchase"),
    F("initial_location_id", "Receive into Location", type="fk", fk="tyre_locations", virtual=True, section="Purchase",
      hint="new tyres only"),
    F("current_status", "Status", type="select", choices=TYRE_STATUS, readonly=True, list=True, filter=True, section="Lifecycle"),
    F("current_vehicle_id", "Vehicle", type="fk", fk="vehicles", readonly=True, list=True, filter=True, section="Lifecycle"),
    F("current_position_id", "Position", type="fk", fk="tyre_positions", readonly=True, list=True, section="Lifecycle"),
    F("current_location_id", "Location", type="fk", fk="tyre_locations", readonly=True, list=True, filter=True,
      section="Lifecycle"),
    F("current_install_odometer", "Install Odometer", type="decimal", readonly=True, section="Lifecycle"),
    F("current_tread_depth", "Current Tread", type="decimal", readonly=True, list=True, section="Lifecycle"),
    F("total_km", "Total KM", type="decimal", readonly=True, list=True, section="Lifecycle"),
    F("retread_count", "Retreads", type="int", readonly=True, list=True, section="Lifecycle"),
    F("scrap_date", "Scrap Date", type="date", readonly=True, section="Lifecycle"),
    F("scrap_reason", "Scrap Reason", readonly=True, section="Lifecycle"),
    F("scrap_value", "Scrap Value", type="money", readonly=True, section="Lifecycle"), remarks()],
    actions=TYRE_ACTIONS, code_field="serial_number", title_field="serial_number",
    label_fields=("serial_number", "brand", "size"), before_save=tyres.tyre_before_save, after_save=tyres.tyre_after_save,
    serialize_extra=tyres.tyre_extra, documents=True, group="Tyres", status_field="current_status",
    subtitle_fields=("brand", "size"), can_delete=False))

register(MasterSpec("tyre_movements", TY.TyreMovement, "Tyre Movements", "tyre", "ti-route", [
    F("tyre_id", "Tyre", type="fk", fk="tyres", list=True, filter=True, readonly=True),
    F("movement_type", "Movement", list=True, filter=True, readonly=True),
    F("movement_date", "Date", type="datetime", list=True, readonly=True),
    F("from_vehicle_id", "From Vehicle", type="fk", fk="vehicles", list=True, filter=True, readonly=True),
    F("to_vehicle_id", "To Vehicle", type="fk", fk="vehicles", list=True, filter=True, readonly=True),
    F("from_position_id", "From Pos.", type="fk", fk="tyre_positions", list=True, readonly=True),
    F("to_position_id", "To Pos.", type="fk", fk="tyre_positions", list=True, readonly=True),
    F("to_location_id", "To Location", type="fk", fk="tyre_locations", list=True, readonly=True),
    F("odometer", "Odometer", type="decimal", list=True, readonly=True),
    F("running_km", "Running KM", type="decimal", list=True, readonly=True),
    F("tread_depth", "Tread", type="decimal", list=True, readonly=True),
    F("status_after", "Status After", list=True, readonly=True), F("reason", "Reason", list=True, readonly=True),
    F("is_override", "Override", type="bool", readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Tyres",
    date_field="movement_date", default_sort="movement_date"))

register(MasterSpec("tyre_retreading", TY.TyreRetreading, "Tyre Retreading", "tyre", "ti-recycle", [
    F("tyre_id", "Tyre", type="fk", fk="tyres", list=True, filter=True, readonly=True),
    F("vendor_id", "Retreader", type="fk", fk="vendors", list=True, filter=True, readonly=True),
    F("sent_date", "Sent", type="date", list=True, readonly=True), F("return_date", "Returned", type="date", list=True, readonly=True),
    F("tread_depth", "Tread Before", type="decimal", list=True, readonly=True),
    F("new_tread_depth", "Tread After", type="decimal", list=True, readonly=True),
    F("retread_type", "Type", list=True, readonly=True), F("cost", "Cost", type="money", list=True, readonly=True),
    F("invoice_number", "Invoice", list=True, readonly=True), F("status", "Status", list=True, filter=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Tyres",
    date_field="sent_date", documents=True))

register(MasterSpec("tyre_inspections", TY.TyreInspection, "Tyre Inspections", "tyre", "ti-zoom-check", [
    F("tyre_id", "Tyre", type="fk", fk="tyres", list=True, filter=True, readonly=True),
    F("inspection_date", "Date", type="date", list=True, readonly=True),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, filter=True, readonly=True),
    F("position_id", "Position", type="fk", fk="tyre_positions", list=True, readonly=True),
    F("odometer", "Odometer", type="decimal", list=True, readonly=True),
    F("tread_depth", "Tread", type="decimal", list=True, readonly=True),
    F("pressure_psi", "Pressure", type="decimal", list=True, readonly=True),
    F("condition", "Condition", list=True, readonly=True), F("damage", "Damage", list=True, readonly=True),
    F("recommended_action", "Action", list=True, readonly=True), F("inspector", "Inspector", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Tyres",
    date_field="inspection_date"))

register(MasterSpec("tyre_maintenance", TY.TyreMaintenance, "Tyre Maintenance", "tyre", "ti-tool", [
    F("tyre_id", "Tyre", type="fk", fk="tyres", list=True, filter=True, readonly=True),
    F("maintenance_type", "Type", list=True, filter=True, readonly=True),
    F("maintenance_date", "Date", type="date", list=True, readonly=True),
    F("vehicle_id", "Vehicle", type="fk", fk="vehicles", list=True, readonly=True),
    F("vendor_id", "Vendor", type="fk", fk="vendors", list=True, readonly=True),
    F("cost", "Cost", type="money", list=True, readonly=True), F("invoice_number", "Invoice", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Tyres",
    date_field="maintenance_date"))

register(MasterSpec("tyre_warranty_claims", TY.TyreWarrantyClaim, "Tyre Warranty Claims", "tyre", "ti-shield", [
    F("claim_number", "Claim No.", list=True, search=True, readonly=True),
    F("tyre_id", "Tyre", type="fk", fk="tyres", list=True, filter=True, readonly=True),
    F("claim_date", "Claim Date", type="date", list=True, readonly=True),
    F("failure_reason", "Failure Reason", list=True, readonly=True),
    F("warranty_provider_id", "Provider", type="fk", fk="vendors", list=True, readonly=True),
    F("claim_amount", "Claimed", type="money", list=True, readonly=True),
    F("approved_amount", "Approved", type="money", list=True, readonly=True),
    F("resolution_type", "Resolution", list=True, readonly=True), F("status", "Status", list=True, filter=True, readonly=True),
    F("resolution_date", "Resolved", type="date", list=True, readonly=True)],
    actions=[Action("resolve", "Resolve Claim", "ti-gavel", "tyre.edit", tyres.resolve_warranty, [
        F("status", "Outcome", type="select", choices=["UNDER_REVIEW", "APPROVED", "REJECTED", "SETTLED"], required=True),
        F("resolution_type", "Resolution", type="select", choices=["REPLACEMENT", "CREDIT", "REJECTED"]),
        F("approved_amount", "Approved Amount", type="money"),
        F("replacement_tyre_id", "Replacement Tyre", type="fk", fk="tyres"),
        F("resolution_date", "Resolution Date", type="date"), F("remarks", "Remarks", type="textarea")],
        visible_when={"status": ["SUBMITTED", "UNDER_REVIEW"]})],
    can_create=False, can_edit=False, can_delete=False, code_field="claim_number", label_fields=("claim_number",),
    group="Tyres", date_field="claim_date", documents=True))

# ═════════════════════════════ SECURITY / ADMIN ═════════════════════════════
def _user_before(ctx, u: S.User, data, is_new):
    pw = data.get("password")
    if is_new and not pw:
        raise BusinessError("Password is required for a new user", "VALIDATION",
                            [{"field": "password", "message": "Required"}])
    if pw:
        validate_password_strength(pw)
        u.password_hash = hash_password(pw)
        u.token_version = (u.token_version or 0) + (0 if is_new else 1)
        u.must_change_password = bool(data.get("must_change_password", is_new))
    if u.is_superuser and not ctx.user.is_superuser:
        raise BusinessError("Only a super user can grant super-user rights")


def _user_after(ctx, u: S.User, data, is_new):
    db = ctx.db
    if "role_ids" in data:
        ids = [int(x) for x in (data.get("role_ids") or [])]
        db.execute(delete(S.user_roles).where(S.user_roles.c.user_id == u.id))
        for rid in ids:
            db.execute(insert(S.user_roles).values(user_id=u.id, role_id=rid))
        audit(db, ctx.user, "ROLE_CHANGE", "users", u.id, new={"role_ids": ids})
    if "branch_ids" in data:
        ids = [int(x) for x in (data.get("branch_ids") or [])]
        db.execute(delete(S.user_branches).where(S.user_branches.c.user_id == u.id))
        for bid in ids:
            db.execute(insert(S.user_branches).values(user_id=u.id, branch_id=bid))
    db.expire(u, ["roles"])


def _user_extra(ctx, u, row):
    row["role_ids"] = [r.id for r in u.roles]
    row["roles_label"] = ", ".join(r.name for r in u.roles)
    row["branch_ids"] = list(ctx.db.execute(select(S.user_branches.c.branch_id).where(
        S.user_branches.c.user_id == u.id)).scalars())
    row.pop("password_hash", None)


def _unlock(ctx, u, data):
    u.failed_attempts, u.locked_until = 0, None
    return {"message": "Unlocked"}


register(MasterSpec("users", S.User, "Users", "admin", "ti-user-shield", [
    F("username", "Username", required=True, maxlen=50, list=True, search=True, readonly_on_edit=True,
      pattern=r"[A-Za-z0-9_.\-]+", pattern_msg="letters, digits, . _ -"),
    F("full_name", "Full Name", required=True, maxlen=150, list=True, search=True),
    F("email", "E-mail", maxlen=150, list=True), F("mobile", "Mobile", maxlen=15),
    F("password", "Password (set / reset)", type="password", virtual=True, hint="min 8 chars, letters + digits"),
    F("must_change_password", "Must change at next login", type="bool"),
    F("is_superuser", "Super User", type="bool", list=True), F("all_branches", "All Branches", type="bool", default=True, list=True),
    F("role_ids", "Roles", type="multi", fk="roles", virtual=True, span=2),
    F("branch_ids", "Restricted to Branches", type="multi", fk="branches", virtual=True, span=2),
    F("last_login_at", "Last Login", type="datetime", readonly=True, list=True),
    F("locked_until", "Locked Until", type="datetime", readonly=True)],
    actions=[Action("unlock", "Unlock", "ti-lock-open", "admin.edit", _unlock)],
    code_field="username", title_field="full_name", label_fields=("username", "full_name"),
    before_save=_user_before, after_save=_user_after, serialize_extra=_user_extra, group="Administration"))


def _role_after(ctx, r: S.Role, data, is_new):
    if "permission_ids" in data:
        ids = [int(x) for x in (data.get("permission_ids") or [])]
        ctx.db.execute(delete(S.role_permissions).where(S.role_permissions.c.role_id == r.id))
        for pid in ids:
            ctx.db.execute(insert(S.role_permissions).values(role_id=r.id, permission_id=pid))
        ctx.db.expire(r, ["permissions"])
        audit(ctx.db, ctx.user, "PERMISSION_CHANGE", "roles", r.id, new={"permission_ids": ids})


register(MasterSpec("roles", S.Role, "Roles", "admin", "ti-users-group", [
    code(30), name(100), F("description", "Description", maxlen=255, span=2),
    F("permission_ids", "Permissions", type="multi", fk="permissions", virtual=True, span=3)],
    after_save=_role_after, serialize_extra=lambda ctx, r, row: row.update(
        permission_ids=[p.id for p in r.permissions], permission_count=len(r.permissions)), group="Administration"))

register(MasterSpec("permissions", S.Permission, "Permissions", "admin", "ti-key", [
    F("code", "Code", list=True, search=True, readonly=True), F("module", "Module", list=True, filter=True, readonly=True),
    F("action", "Action", list=True, filter=True, readonly=True), F("description", "Description", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=False, label_fields=("code",), group="Administration",
    default_sort="code", default_dir="asc", page_size=200))

register(MasterSpec("audit_logs", S.AuditLog, "Audit Log", "audit", "ti-history-toggle", [
    F("created_at", "When", type="datetime", list=True, readonly=True),
    F("username", "User", list=True, search=True, filter=True, readonly=True),
    F("action", "Action", list=True, filter=True, readonly=True),
    F("entity_type", "Entity", list=True, filter=True, search=True, readonly=True),
    F("entity_id", "Entity ID", list=True, filter=True, readonly=True),
    F("reason", "Reason", list=True, readonly=True), F("ip_address", "IP", list=True, readonly=True),
    F("old_values", "Old Values", type="json", readonly=True), F("new_values", "New Values", type="json", readonly=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id",), group="Administration",
    date_field="created_at", default_sort="created_at", page_size=50))


def _approve(ctx, req, data):
    from app.services import approvals
    approvals.decide(ctx.db, ctx.user, req.id, True, data.get("reason"))
    return {"message": f"Request {req.status}"}


def _reject(ctx, req, data):
    from app.services import approvals
    approvals.decide(ctx.db, ctx.user, req.id, False, data.get("reason"))
    return {"message": "Rejected"}


register(MasterSpec("approval_requests", FI.ApprovalRequest, "Approvals", "approval", "ti-checklist", [
    F("created_at", "Requested", type="datetime", list=True, readonly=True),
    F("action_type", "Action", list=True, filter=True, readonly=True),
    F("entity_type", "Entity", list=True, readonly=True), F("entity_id", "ID", type="int", list=True, readonly=True),
    F("summary", "Summary", list=True, search=True, readonly=True), F("amount", "Amount", type="money", list=True, readonly=True),
    F("status", "Status", list=True, filter=True, readonly=True),
    F("current_level", "Level", type="int", list=True, readonly=True),
    F("required_levels", "Levels", type="int", list=True, readonly=True),
    F("requested_by", "Requested By", type="fk", fk="users", list=True, readonly=True)],
    actions=[Action("approve", "Approve", "ti-check", "approval.approve", _approve,
                    [F("reason", "Remarks", type="textarea")], visible_when={"status": ["PENDING"]}, style="act"),
             Action("reject", "Reject", "ti-x", "approval.approve", _reject,
                    [F("reason", "Reason", type="textarea", required=True)], visible_when={"status": ["PENDING"]},
                    style="del", reason_required=True)],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("id", "action_type"),
    group="Administration", status_field="status"))


def _mark_read(ctx, n, data):
    n.is_read, n.read_by, n.read_at = True, ctx.user.id, now()
    return {"message": "Marked read"}


register(MasterSpec("notifications", S.Notification, "Alerts & Notifications", "notification", "ti-bell", [
    F("created_at", "When", type="datetime", list=True, readonly=True),
    F("severity", "Severity", list=True, filter=True, readonly=True),
    F("event_type", "Event", list=True, filter=True, readonly=True),
    F("title", "Title", list=True, search=True, readonly=True), F("message", "Message", list=True, readonly=True),
    F("is_read", "Read", type="bool", list=True, filter=True, readonly=True),
    F("channels_sent", "Channels", readonly=True), F("link_url", "Link", readonly=True)],
    actions=[Action("read", "Mark Read", "ti-check", "notification.view", _mark_read, visible_when={"is_read": [False]})],
    can_create=False, can_edit=False, can_delete=False, code_field=None, label_fields=("title",), group="Administration",
    default_sort="created_at", page_size=50))

register(MasterSpec("documents", S.Document, "Documents", "document", "ti-files", [
    F("document_type", "Type", type="lookup", lookup="DOCUMENT_TYPE", list=True, filter=True, readonly=True),
    F("entity_type", "Entity", list=True, filter=True, readonly=True),
    F("entity_id", "Entity ID", type="int", list=True, filter=True, readonly=True),
    F("file_name", "File", list=True, search=True, readonly=True), F("version", "Version", type="int", list=True, readonly=True),
    F("size_bytes", "Size", type="int", list=True, readonly=True),
    F("uploaded_at", "Uploaded", type="datetime", list=True, readonly=True),
    F("uploaded_by", "By", type="fk", fk="users", list=True, readonly=True), F("remarks", "Remarks", list=True, readonly=True)],
    can_create=False, can_edit=False, can_delete=True, code_field=None, label_fields=("file_name",), group="Administration",
    default_sort="uploaded_at"))


def menu() -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """Navigation (spec §61): (group, [(label, url, icon, permission)])."""
    m = lambda k, label=None: (label or _R[k].title, f"/masters/{k}", _R[k].icon, _R[k].perm("view"))  # noqa: E731
    return [
        ("Dashboard", [("Executive Dashboard", "/dashboard", "ti-dashboard", "dashboard.view"),
                       ("Alerts", "/masters/notifications", "ti-bell", "notification.view"),
                       ("Approvals", "/masters/approval_requests", "ti-checklist", "approval.view")]),
        ("Organization", [m("companies"), m("branches"), m("departments"), m("locations", "Locations / Godowns"),
                          m("states"), m("districts"), m("rtos")]),
        ("Fleet", [m("vehicles", "Vehicles"), m("cost_categories", "Vehicle Categories"),
                   m("sub_categories", "Vehicle Sub-categories"), m("sub_category_attributes", "Sub-category Attributes"),
                   m("cost_centers", "Cost Centers"), m("vehicle_cc_history", "Vehicle Cost Center History"),
                   m("odometer_readings")]),
        ("Drivers", [m("drivers", "Driver Master"), ("Driver Documents", "/masters/documents?f_entity_type=drivers",
                                                     "ti-files", "driver.view"),
                     ("Driver Renewals", "/compliance?applies=DRIVER", "ti-certificate", "compliance.view")]),
        ("Compliance", [("Renewal Dashboard / Calendar", "/compliance", "ti-calendar-due", "compliance.view"),
                        m("insurance_policies", "Insurance"),
                        ("Road Tax / QTAX", "/masters/vehicle_renewals?category=TAX", "ti-receipt-tax", "compliance.view"),
                        ("National / State Permit", "/masters/vehicle_renewals?category=PERMIT", "ti-map-route", "compliance.view"),
                        ("Fitness", "/masters/vehicle_renewals?category=FITNESS", "ti-heartbeat", "compliance.view"),
                        ("PUCC", "/masters/vehicle_renewals?category=PUCC", "ti-leaf", "compliance.view"),
                        ("PESO / Hazardous", "/masters/vehicle_renewals?category=PESO", "ti-flame", "compliance.view"),
                        m("vehicle_renewals", "All Renewals"), m("renewal_assignments"),
                        m("renewal_types"), m("renewal_rules"), m("renewal_history")]),
        ("Contracts & Income", [m("customers"), m("contracts"), m("invoices", "Invoices"),
                                ("Receivables", "/reports?r=receivables", "ti-report-money", "report.view"),
                                ("Receipts (bank credits)", "/finance/reconciliation?dir=CR", "ti-cash", "finance.view")]),
        ("Finance", [m("banks"), m("bank_accounts"), m("bank_transactions", "Bank Statements"),
                     ("Reconciliation Workbench", "/finance/reconciliation", "ti-arrows-join-2", "finance.view"),
                     ("Credit Matching", "/finance/reconciliation?dir=CR", "ti-arrow-down-left", "finance.view"),
                     ("Debit Allocation", "/finance/reconciliation?dir=DR", "ti-arrow-up-right", "finance.view"),
                     m("financial_links", "Financial Links"), m("bank_allocations"), m("recon_history"),
                     m("credit_types"), m("expense_types"), m("matching_rules")]),
        ("Fuel", [m("fuel_types"), m("fuel_stations"), m("fuel_cards"), m("fuel_transactions"),
                  ("Fuel Imports", "/imports?type=FUEL", "ti-file-import", "import.view"),
                  ("Fuel Reports", "/reports?r=fuel_efficiency", "ti-chart-line", "report.view")]),
        ("Toll", [("Toll Providers", "/masters/providers?f_provider_type=TOLL", "ti-plug", "master.view"),
                  m("toll_plazas"), m("toll_plaza_sync_runs", "Toll Plaza Internet Sync"),
                  m("toll_vehicle_mappings"), m("toll_transactions"),
                  ("Toll Review (unmatched)", "/masters/toll_transactions?f_status=VEHICLE_UNMATCHED,PLAZA_UNMATCHED,VEHICLE_MATCHED",
                   "ti-alert-circle", "toll.view"),
                  ("Toll Imports", "/imports?type=TOLL", "ti-file-import", "import.view"),
                  ("Toll Reports", "/reports?r=toll_summary", "ti-chart-bar", "report.view")]),
        ("Maintenance", [m("maintenance_types"), m("job_cards", "Job Cards"),
                         ("Maintenance Reports", "/reports?r=maintenance_summary", "ti-chart-bar", "report.view")]),
        ("Tyres", [m("tyres", "Tyre Master"), ("Tyre Stock", "/masters/tyres?f_current_status=NEW,IN_STOCK,IN_GODOWN,REMOVED,RETREADED",
                                               "ti-building-warehouse", "tyre.view"),
                   ("Tyre Dashboard", "/tyres/dashboard", "ti-steering-wheel", "tyre.view"),
                   m("tyre_movements", "Tyre Movements / Transfers"), m("tyre_inspections"), m("tyre_retreading"),
                   m("tyre_warranty_claims", "Warranty"), m("tyre_maintenance"),
                   ("Scrap / Disposal", "/masters/tyres?f_current_status=SCRAPPED,SOLD,LOST", "ti-trash", "tyre.view"),
                   m("tyre_positions"), m("tyre_layouts"), m("tyre_locations"),
                   ("Tyre Reports", "/reports?r=tyre_cost", "ti-chart-dots", "report.view")]),
        ("Vendors", [m("vendors", "Suppliers / Service Providers"), m("expenses", "Vendor Invoices / Expenses")]),
        ("Imports", [("Import Wizard", "/imports", "ti-file-import", "import.run"),
                     m("import_templates", "Import Templates / Builder"), m("providers"), m("value_mappings"),
                     m("import_batches", "Import Batches / History"), m("import_errors")]),
        ("Reports", [("Report Centre", "/reports", "ti-report-analytics", "report.view"),
                     ("Profitability", "/reports?r=profitability", "ti-chart-arrows", "report.view"),
                     ("Category Costs", "/reports?r=category_costs", "ti-chart-pie", "report.view")]),
        ("Administration", [m("users"), m("roles"), m("permissions"), m("lookup_values", "Master Configuration (Lookups)"),
                            m("units"), m("transaction_types"), m("business_rules", "System Settings / Rules"),
                            m("notification_rules"), m("approval_rules"), m("api_integrations", "API Integrations"),
                            m("audit_logs"), m("documents")]),
    ]


# ── Module cards (home page → module page → form), in the SSTL-ERP card-navigation style ──────────────────────
# (menu group, url key, card colour, icon, description). Colours are the SSTL-ERP module card variants.
MODULES = [
    ("Dashboard", "dashboard", "deep-blue", "ti-layout-dashboard", "Executive dashboard, alerts and approvals waiting for you."),
    ("Fleet", "fleet", "indigo", "ti-truck", "Vehicles, categories, cost centers, classification history and odometer."),
    ("Drivers", "drivers", "green", "ti-id-badge-2", "Driver master, licences, documents and driver renewals."),
    ("Compliance", "compliance", "red", "ti-certificate", "Renewal calendar, insurance, tax, permits, fitness, PUCC and PESO."),
    ("Contracts & Income", "contracts", "teal", "ti-file-certificate", "Customers, contracts, invoices, receivables and receipts."),
    ("Finance", "finance", "violet", "ti-building-bank", "Banks, statements, reconciliation, allocations and matching rules."),
    ("Fuel", "fuel", "orange", "ti-gas-station", "Fuel types, stations, cards, transactions, imports and efficiency."),
    ("Toll", "toll", "amber", "ti-road", "Toll providers, plazas, FASTag mappings, transactions and review."),
    ("Maintenance", "maintenance", "magenta", "ti-tool", "Maintenance types, job cards with parts and labour, cost reports."),
    ("Tyres", "tyres", "cyan", "ti-wheel", "Tyre master, stock, fitments, movements, retreading and warranty."),
    ("Vendors", "vendors", "rose", "ti-building-store", "Suppliers, service providers and vendor invoices / expenses."),
    ("Imports", "imports", "sky", "ti-file-import", "Excel import wizard, templates, providers, mappings and history."),
    ("Reports", "reports", "slate", "ti-report-analytics", "Report centre, profitability and category cost analysis."),
    ("Organization", "organization", "purple", "ti-building", "Companies, branches, departments, locations, states and RTOs."),
    ("Administration", "admin", "deep-blue", "ti-user-shield", "Users, roles, permissions, settings, lookups and audit log."),
]
# Card colours used in turn for the form cards inside a module page.
CARD_COLOURS = ["deep-blue", "red", "green", "orange", "purple", "magenta", "teal", "cyan", "amber", "violet", "rose", "indigo"]

ITEM_DESC = {
    "/dashboard": "Fleet, compliance, finance and operations at a glance.",
    "/compliance": "Upcoming and overdue renewals with a calendar view.",
    "/finance/reconciliation": "Match bank credits and allocate debits to cost centers.",
    "/imports": "Upload an Excel/CSV statement, map columns, preview and import.",
    "/tyres/dashboard": "Axle-wise view of fitted tyres with tread and history.",
    "/reports": "All reports with Excel, CSV, PDF export and print.",
}


# Card text for the form screens (by master key).
SCREEN_DESC = {
    "notifications": "Renewal, maintenance and exception alerts raised for you.",
    "approval_requests": "Requests waiting for approval, with approve / reject.",
    "vehicles": "Vehicle register: identity, classification, ownership, capacity and fuel.",
    "sub_category_attributes": "Technical fields captured per vehicle sub-category.",
    "vehicle_cc_history": "Effective-dated category / cost-center history per vehicle.",
    "odometer_readings": "Odometer readings with chronology checks.",
    "drivers": "Driver details, licence, engagement and contact.",
    "insurance_policies": "Vehicle insurance policies, premium and renewal.",
    "vehicle_renewals": "Every vehicle renewal: tax, permit, fitness, PUCC, PESO.",
    "renewal_assignments": "Which renewals apply to each vehicle.",
    "renewal_types": "Renewal types and their reminder settings.",
    "renewal_rules": "Rules that assign renewal types to vehicle categories.",
    "renewal_history": "History of completed renewals.",
    "customers": "Customer master with GST, contact and credit terms.",
    "contracts": "Customer contracts, rates, period and allocated vehicles.",
    "invoices": "Invoices, credit notes and advances with vehicle allocation.",
    "banks": "Bank master.",
    "bank_accounts": "Company bank accounts and statement templates.",
    "bank_transactions": "Imported bank statement lines and their status.",
    "financial_links": "Links settling bank lines against invoices and costs.",
    "bank_allocations": "Bank debits allocated to cost centers.",
    "recon_history": "Every reconciliation action, for audit.",
    "credit_types": "Classification types for bank credits.",
    "expense_types": "Expense heads for debits and vendor invoices.",
    "matching_rules": "Auto-suggestion rules for reconciliation.",
    "fuel_types": "Diesel, petrol, CNG, LPG and other fuels.",
    "fuel_stations": "Fuel stations / pumps and their provider.",
    "fuel_cards": "Fuel / fleet cards and the vehicles they belong to.",
    "fuel_transactions": "Fuel fills with quantity, rate and odometer.",
    "toll_plazas": "Toll plaza master — fetch from the internet: toll ID, name, place and state.",
    "toll_plaza_sync_runs": "History of toll plaza fetches from OpenStreetMap / data.gov.in / FASTag APIs.",
    "toll_vehicle_mappings": "FASTag / tag-to-vehicle mappings per provider.",
    "toll_transactions": "Toll deductions matched to vehicles and plazas.",
    "maintenance_types": "Service and repair types with due intervals.",
    "job_cards": "Workshop job cards with parts, labour and downtime.",
    "tyres": "Tyre register: serial, brand, size, status and cost.",
    "tyre_movements": "Fit, remove, rotate and transfer history of tyres.",
    "tyre_inspections": "Tread depth and pressure inspections.",
    "tyre_retreading": "Tyres sent for retreading and their return.",
    "tyre_warranty_claims": "Warranty claims and settlements.",
    "tyre_maintenance": "Puncture and repair records.",
    "tyre_positions": "Wheel positions used in tyre layouts.",
    "tyre_locations": "Godowns and places where tyres are stored.",
    "vendors": "Suppliers, workshops and service providers.",
    "expenses": "Vendor invoices / expenses split across cost centers.",
    "import_templates": "Column mappings and rules for each statement layout.",
    "providers": "Banks, toll, fuel, insurance and service providers.",
    "value_mappings": "Translate provider values to ERP masters.",
    "import_batches": "Every import run with counts and status.",
    "import_errors": "Rows that failed to import, with reasons.",
    "companies": "Company master with GST and address.",
    "branches": "Branches of each company.",
    "departments": "Departments for users and cost centers.",
    "locations": "Locations, godowns, workshops and warehouses.",
    "states": "States with GST state codes.",
    "districts": "Districts by state.",
    "rtos": "Regional transport offices.",
    "users": "User logins, roles and branch access.",
    "roles": "Roles and their permissions.",
    "permissions": "Permission list used by roles.",
    "lookup_values": "Drop-down lists used across the forms.",
    "units": "Units of measure.",
    "transaction_types": "Transaction types for finance and imports.",
    "business_rules": "System settings and configurable business rules.",
    "notification_rules": "When and to whom alerts are sent.",
    "approval_rules": "Which actions need approval and by whom.",
    "audit_logs": "Who changed what and when.",
    "documents": "All uploaded documents and versions.",
}


def _item_desc(label: str, url: str) -> str:
    if url in ITEM_DESC:
        return ITEM_DESC[url]
    if url.startswith("/masters/") and "?" not in url and url.rsplit("/", 1)[-1] in SCREEN_DESC:
        return SCREEN_DESC[url.rsplit("/", 1)[-1]]
    if url.startswith("/masters/"):
        key = url.split("?")[0].rsplit("/", 1)[-1]
        spec = _R.get(key)
        if spec and spec.description and "?" not in url:
            return spec.description
        if "?" in url:
            return f"{label} — filtered view of {spec.title if spec else key}."
        return f"Add, edit, search and export {label.lower()}."
    if url.startswith("/reports"):
        return f"{label} report with export and print."
    if url.startswith("/imports"):
        return f"{label}: upload and import statement files."
    if url.startswith("/finance/reconciliation"):
        return f"{label} in the reconciliation workbench."
    if url.startswith("/compliance"):
        return f"{label} — due and overdue items."
    return label


def modules(has=lambda perm: True) -> list[dict]:
    """Module cards for the home page; each with the form cards the user is allowed to open."""
    groups = dict(menu())
    out = []
    for group, key, colour, icon, desc in MODULES:
        items = [{"label": label, "url": url, "icon": ic, "perm": perm, "desc": _item_desc(label, url),
                  "colour": CARD_COLOURS[i % len(CARD_COLOURS)]}
                 for i, (label, url, ic, perm) in enumerate(groups.get(group, [])) if has(perm)]
        if items:
            out.append({"key": key, "title": group, "colour": colour, "icon": icon, "desc": desc, "items": items})
    return out


def module_for(path: str, query: str, mods: list[dict]) -> dict | None:
    """The module a page belongs to (exact URL match first, then path only)."""
    full = path + ("?" + query if query else "")
    for exact in (True, False):
        for m in mods:
            for it in m["items"]:
                u = it["url"]
                if (u == full) if exact else (u.split("?")[0] == path):
                    return m
    return None
