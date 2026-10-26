"""Pydantic schemas and data models for Forager and HubSpot integration."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl


class HubSpotWebhookEvent(BaseModel):
    """Model representing an individual event sent in a HubSpot webhook payload."""
    eventId: Optional[Any] = None
    subscriptionId: Optional[Any] = None
    portalId: Optional[int] = None
    appId: Optional[int] = None
    occurredAt: Optional[int] = None
    subscriptionType: str = Field(
        ...,
        description="Event type, e.g. 'company.creation' or 'contact.creation'",
    )
    attemptNumber: Optional[int] = 0
    objectId: int = Field(
        ...,
        description="CRM Record ID of the target company or contact",
    )
    propertyName: Optional[str] = None
    propertyValue: Optional[Any] = None
    changeSource: Optional[str] = None


class EnrichedCompany(BaseModel):
    """Standardized normalized company representation mapped from Forager."""
    id: Optional[str] = None
    name: Optional[str] = None
    domain: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    revenue: Optional[int] = None
    employee_count: Optional[int] = None
    employee_range: Optional[str] = None
    linkedin_url: Optional[str] = None
    founded_date: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    extra_details: Dict[str, Any] = Field(default_factory=dict)

    def to_hubspot_properties(self) -> Dict[str, str]:
        """Convert non-empty company properties to HubSpot CRM dictionary."""
        props: Dict[str, str] = {}
        if self.name:
            props["name"] = self.name
        if self.domain:
            props["domain"] = self.domain
        if self.website:
            props["website"] = self.website
        if self.description:
            props["description"] = self.description
        if self.revenue is not None:
            props["annualrevenue"] = str(self.revenue)
        if self.employee_count is not None:
            props["numberofemployees"] = str(self.employee_count)
        if self.linkedin_url:
            props["linkedin_company_page"] = self.linkedin_url
        if self.city:
            props["city"] = self.city
        if self.state:
            props["state"] = self.state
        if self.country:
            props["country"] = self.country
        return props


class EnrichedContact(BaseModel):
    """Standardized normalized contact representation mapped from Forager."""
    id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    job_title: Optional[str] = None
    linkedin_url: Optional[str] = None
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    # Nice-to-have extra details surfaced by Forager
    headline: Optional[str] = None
    summary_about: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    photo_url: Optional[str] = None
    extra_details: Dict[str, Any] = Field(default_factory=dict)

    def to_hubspot_properties(self) -> Dict[str, str]:
        """Convert non-empty contact properties to standard HubSpot CRM dictionary."""
        props: Dict[str, str] = {}
        if self.first_name:
            props["firstname"] = self.first_name
        if self.last_name:
            props["lastname"] = self.last_name
        if self.email:
            props["email"] = self.email
        if self.phone:
            props["phone"] = self.phone
        if self.job_title:
            props["jobtitle"] = self.job_title
        if self.company_name:
            props["company"] = self.company_name
        if self.linkedin_url:
            props["hs_linkedin_url"] = self.linkedin_url
        if self.city:
            props["city"] = self.city
        if self.state:
            props["state"] = self.state
        if self.country:
            props["country"] = self.country
        return props

    def calculate_completeness(self) -> Dict[str, Any]:
        """Calculate field population completeness and report missing fields."""
        fields_to_check = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "job_title": self.job_title,
            "linkedin_url": self.linkedin_url,
            "company_name": self.company_name,
            "company_domain": self.company_domain,
            "company_linkedin_url": self.company_linkedin_url,
            "email": self.email,
            "phone": self.phone,
            "city": self.city,
            "state": self.state,
            "country": self.country,
        }
        populated = [k for k, v in fields_to_check.items() if v]
        missing = [k for k, v in fields_to_check.items() if not v]
        percentage = round((len(populated) / len(fields_to_check)) * 100, 1)
        return {
            "total_fields": len(fields_to_check),
            "populated_count": len(populated),
            "populated_fields": populated,
            "missing_count": len(missing),
            "missing_fields": missing,
            "completeness_percentage": percentage,
        }


class CompanyEnrichmentReport(BaseModel):
    """Report detailing the result of enriching a company."""
    status: str
    company_id: str
    company_name: Optional[str] = None
    domain: Optional[str] = None
    properties_updated: List[str] = Field(default_factory=list)
    contacts_discovered_count: int = 0
    contacts_enriched_count: int = 0
    errors: List[str] = Field(default_factory=list)


class ContactEnrichmentReport(BaseModel):
    """Report detailing the result of enriching an individual contact."""
    status: str
    contact_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    job_title: Optional[str] = None
    company_associated_id: Optional[str] = None
    properties_updated: List[str] = Field(default_factory=list)
    completeness: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class EnrichCompanyRequest(BaseModel):
    """Manual request payload to enrich a company."""
    company_id: Optional[str] = None
    domain: Optional[str] = None
    discover_contacts: bool = True


class EnrichContactRequest(BaseModel):
    """Manual request payload to enrich a contact."""
    contact_id: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None


class DiscoverContactsRequest(BaseModel):
    """Request payload to discover contacts at a company."""
    domain: str
    company_id: Optional[str] = None
    job_titles: Optional[List[str]] = None
    limit: Optional[int] = 5


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str = "ok"
    app: str = "forager-hubspot-enrichment"
    version: str = "0.1.0"
    environment: str = "development"
