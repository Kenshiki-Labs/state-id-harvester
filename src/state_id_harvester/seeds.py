"""Curated entry points are leads, not assertions of current design or complete coverage."""

STATE_DOMAINS: dict[str, str] = {
    "AL": "alea.gov",
    "AK": "alaska.gov",
    "AZ": "azdot.gov",
    "AR": "arkansas.gov",
    "CA": "ca.gov",
    "CO": "colorado.gov",
    "CT": "ct.gov",
    "DE": "delaware.gov",
    "DC": "dc.gov",
    "FL": "flhsmv.gov",
    "GA": "georgia.gov",
    "HI": "hawaii.gov",
    "ID": "idaho.gov",
    "IL": "ilsos.gov",
    "IN": "in.gov",
    "IA": "iowadot.gov",
    "KS": "ks.gov",
    "KY": "ky.gov",
    "LA": "la.gov",
    "ME": "maine.gov",
    "MD": "maryland.gov",
    "MA": "mass.gov",
    "MI": "michigan.gov",
    "MN": "mn.gov",
    "MS": "ms.gov",
    "MO": "mo.gov",
    "MT": "mt.gov",
    "NE": "nebraska.gov",
    "NV": "nv.gov",
    "NH": "nh.gov",
    "NJ": "nj.gov",
    "NM": "nm.gov",
    "NY": "ny.gov",
    "NC": "nc.gov",
    "ND": "nd.gov",
    "OH": "ohio.gov",
    "OK": "oklahoma.gov",
    "OR": "oregon.gov",
    "PA": "pa.gov",
    "RI": "ri.gov",
    "SC": "sc.gov",
    "SD": "sd.gov",
    "TN": "tn.gov",
    "TX": "texas.gov",
    "UT": "utah.gov",
    "VT": "vermont.gov",
    "VA": "virginia.gov",
    "WA": "wa.gov",
    "WV": "wv.gov",
    "WI": "wisconsindot.gov",
    "WY": "wyoming.gov",
}

# Federal is a separate collection, not a 52nd state jurisdiction.
FEDERAL_CODE = "US_FED"
COLLECTION_DOMAINS = {**STATE_DOMAINS, FEDERAL_CODE: "gov"}
FEDERAL_PUBLISHER_HOSTS = frozenset(
    {
        "nvlpubs.nist.gov",
        "csrc.nist.gov",
        "www.cbp.gov",
        "cbp.gov",
        "www.uscis.gov",
        "uscis.gov",
    }
)
FEDERAL_LANDING_PAGES = [
    "https://csrc.nist.gov/pubs/fips/201-3/final",
    "https://www.cbp.gov/travel/travel-industry-personnel",
    "https://www.uscis.gov/i-9-central/form-i-9-acceptable-documents",
]
FEDERAL_SEED_PDFS = [
    "https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.201-3.pdf",
    "https://www.cbp.gov/sites/default/files/assets/documents/2023-Nov/Carrier%20Information%20Guide%20ENGLISH.pdf",
    "https://www.uscis.gov/sites/default/files/document/guides/GreenCard_Comparison_EN.PDF",
    "https://www.uscis.gov/sites/default/files/document/guides/EAD_Comparison_EN.pdf",
    "https://www.txdmv.gov/sites/default/files/body-files/FDR_Level_I_Job_Aid_2018.pdf",
]


def collection_landing_pages(code: str) -> list[str]:
    return FEDERAL_LANDING_PAGES if code == FEDERAL_CODE else LANDING_PAGES[code]


def collection_pdf_seeds(code: str) -> list[str]:
    return FEDERAL_SEED_PDFS if code == FEDERAL_CODE else GOLDEN_SEED_PDFS.get(code, [])


# Official issuer entry points. The crawler only follows public HTTPS .gov links.
LANDING_PAGES: dict[str, list[str]] = {
    "AL": ["https://www.alea.gov/dps/driver-license"],
    "AK": ["https://dmv.alaska.gov/"],
    "AZ": ["https://azdot.gov/mvd/services/driver-services/driver-license-information"],
    "AR": ["https://www.dfa.arkansas.gov/driver-services/"],
    "CA": ["https://www.dmv.ca.gov/portal/driver-licenses-identification-cards/"],
    "CO": ["https://dmv.colorado.gov/"],
    "CT": ["https://portal.ct.gov/dmv/licenses-permits-ids"],
    "DE": ["https://dmv.de.gov/DriverServices/"],
    "DC": ["https://dmv.dc.gov/service/driver-licenses"],
    "FL": ["https://www.flhsmv.gov/driver-licenses-id-cards/"],
    "GA": ["https://dds.georgia.gov/"],
    "HI": ["https://hidot.hawaii.gov/hawaiis-drivers-license/"],
    "ID": ["https://itd.idaho.gov/itddmv/"],
    "IL": ["https://www.ilsos.gov/departments/drivers/drivers_license/home.html"],
    "IN": ["https://www.in.gov/bmv/licenses-permits-ids/"],
    "IA": ["https://iowadot.gov/drivers-licenses-ids"],
    "KS": ["https://www.ksrevenue.gov/dovindex.html"],
    "KY": ["https://drive.ky.gov/Drivers/Pages/default.aspx"],
    "LA": ["https://www.expresslane.org/drivers/"],
    "ME": ["https://www.maine.gov/sos/bmv/licenses"],
    "MD": ["https://mva.maryland.gov/Pages/default.aspx"],
    "MA": [
        "https://www.mass.gov/info-details/massachusetts-license-and-identification-card-security"
    ],
    "MI": ["https://www.michigan.gov/sos/license-id/license-and-id-information"],
    "MN": ["https://dps.mn.gov/divisions/dvs"],
    "MS": ["https://www.driverservicebureau.dps.ms.gov/"],
    "MO": ["https://dor.mo.gov/driver-license/"],
    "MT": ["https://mvdmt.gov/"],
    "NE": ["https://dmv.nebraska.gov/dl/driver-licensing-services"],
    "NV": ["https://dmv.nv.gov/dlsecurity.htm"],
    "NH": ["https://www.dmv.nh.gov/drivers-licensenon-driver-ids"],
    "NJ": ["https://www.nj.gov/mvc/license/"],
    "NM": ["https://www.mvd.newmexico.gov/"],
    "NY": ["https://dmv.ny.gov/driver-license"],
    "NC": ["https://www.ncdot.gov/dmv/license-id/Pages/default.aspx"],
    "ND": ["https://www.dot.nd.gov/driver/driver-license"],
    "OH": ["https://www.bmv.ohio.gov/dl-real-id.aspx"],
    "OK": ["https://oklahoma.gov/service/all-pages/renew-and-replace-driver-online.html"],
    "OR": ["https://www.oregon.gov/odot/DMV/pages/driverid/samplecards.aspx"],
    "PA": [
        "https://www.pa.gov/agencies/dmv/driver-services/licenses-and-photo-ids/new-driver-license-design"
    ],
    "RI": ["https://dmv.ri.gov/licenses-permits-ids"],
    "SC": ["https://www.scdmvonline.com/Driver-Services/Drivers-License"],
    "SD": ["https://dps.sd.gov/driver-licensing"],
    "TN": ["https://www.tn.gov/safety/driver-services.html"],
    "TX": ["https://www.dps.texas.gov/news/dps-rolls-out-new-driver-license-design"],
    "UT": ["https://dld.utah.gov/"],
    "VT": ["https://dmv.vermont.gov/licenses"],
    "VA": ["https://www.dmv.virginia.gov/licenses-ids"],
    "WA": ["https://dol.wa.gov/driver-licenses-and-permits"],
    "WV": ["https://transportation.wv.gov/DMV/Drivers/Pages/default.aspx"],
    "WI": ["https://wisconsindot.gov/Pages/dmv/license-drvs/how-to-apply/mailed.aspx"],
    "WY": ["https://www.dot.state.wy.us/home/driver_license_records.html"],
}

# A small, explicit exception list for official legacy government hosts, including redirects.
# No generic .com/.org/.us wildcard is permitted.
LEGACY_OFFICIAL_HOSTS = frozenset(
    {
        "www.dot.state.wy.us",
        "dot.state.wy.us",
        "www.expresslane.org",
        "expresslane.org",
        "www.scdmvonline.com",
        "scdmvonline.com",
    }
)

GOLDEN_SEED_PDFS: dict[str, list[str]] = {
    "FL": ["https://www.flhsmv.gov/pdf/newdl/retailguide_aug2020.pdf"],
    "TX": [
        "https://www.dps.texas.gov/internetforms/getForm.ashx?id=DL-73.pdf",
        "https://www.dps.texas.gov/DriverLicense/documents/newDLIDCards.pdf",
        "https://www.txdmv.gov/sites/default/files/body-files/FDR_Level_I_Job_Aid_2018.pdf",
    ],
    "WA": [
        "https://lcb.wa.gov/sites/default/files/publications/licensing/RVP/RVP_Trainers-Guide-English_2018.pdf",
        "https://www.wsp.wa.gov/wp-content/uploads/2023/10/08_licensing.pdf",
    ],
    "VA": ["https://apps.dlas.virginia.gov/user_db/frmvscc.aspx?viewid=644"],
    "DC": [
        "https://dmv.dc.gov/sites/default/files/dc/sites/dmv/page_content/attachments/NewLook_NewSecurity_SameYou_OnePager_Card5.pdf"
    ],
    "OH": ["https://www.bmv.ohio.gov/links/newDL-ID-FACT-SHEET.pdf"],
    "OR": ["https://www.oregon.gov/odot/Forms/DMV/7022_27_2.pdf"],
    "NE": ["https://dmv.nebraska.gov/sites/default/files/doc/dls/2026_Nebraska_DLID_Brochure.pdf"],
    "AK": ["https://dmv.alaska.gov/media/szxjxo0b/onepager_alaska-hd.pdf"],
    "PA": [
        "https://www.pa.gov/content/dam/copapwp-pagov/en/dmv/documents/business-partners/driver-and-vehicle-services-bulletin/bulletin%2022-11%20special%20edition%20updated%20design%20for%20pa%20driver%20license%20and%20id.pdf"
    ],
    "WY": [
        "https://wyoleg.gov/InterimCommittee/2022/08-202208232-04DriverLicense_JTCAugust2022.pdf"
    ],
    "CA": ["https://www.chp.ca.gov/siteassets/policy/hpm/hpm-82.6/hpm-82.6-ch-7.pdf"],
}

DORK_TEMPLATES = [
    'site:{domain} filetype:pdf ("security features" OR "polycarbonate" OR "tactile") '
    '("driver license" OR "identification card")',
    'site:{domain} filetype:pdf ("ghost" OR "ultraviolet" OR "microprinting" OR "look-through") '
    '("alcohol" OR "liquor" OR "cannabis" OR "server" OR "retailer")',
    'site:{domain} filetype:pdf ("Dynamic Look Through" OR "Multiple Laser Image" OR '
    '"guilloche" OR "365 nm" OR "AAMVA")',
    'site:{domain} filetype:pdf ("polycarbonate" OR "IDEMIA" OR "Thales" OR "Veridos") '
    '("driver license")',
]
