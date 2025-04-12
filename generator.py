import argparse
import copy
import logging.config
import os
import pprint
import re
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator, Sequence, Any, Generator

import bs4
import requests
import stringcase
import yaml
from requests import HTTPError

log = logging.getLogger(f"uexcorp-openapi.{__name__}")

logging_config_file = Path(__file__).parent / "config" / "logging.ini"
logging.config.fileConfig(logging_config_file.absolute())


@dataclass
class Settings:
    base_path = "https://api.uexcorp.space/2.0"
    docs_path = "https://uexcorp.space/api/documentation/"
    get_templated_paths: bool = False
    api_cache: bool = False


def create_api_session() -> requests.Session:
    app_token = os.environ.get("APP_TOKEN")
    if not app_token:
        log.debug("environment: %s", os.environ)
        raise Exception("APP_TOKEN not found in environment variables")

    user_token = os.environ.get("USER_TOKEN")
    if not user_token:
        log.debug("environment: %s", os.environ)
        raise Exception("USER_TOKEN not found in environment variables")

    api_session = requests.Session()
    api_session.verify = False
    api_session.headers.update({
        "Authorization": "Bearer " + app_token,
        "secret_key": user_token,
    })

    return api_session


def create_cache_key(_str: str) -> str:
    _str = _str.strip("/")
    _str = _str.replace("/", "-")
    _str = _str.replace("?", "__")
    _str = _str.replace("=", "--")
    _str = _str.replace("&", "__")
    return _str


def get_from_cache_or_request(session: requests.Session, url: str, settings: Settings) -> str:
    url_parts = urllib.parse.urlparse(url)
    path_part = create_cache_key(url_parts.path)
    query_part = create_cache_key(url_parts.query)
    cache_key = f"{path_part}__{query_part}" if query_part else path_part
    ext = "json" if "documentation" not in url_parts.path else "html"
    cache_path = Path(__file__).parent / "cache" / f"{cache_key}.{ext}"
    if cache_path.exists() and settings.api_cache:
        log.debug(f"using cache for {url}")
        return cache_path.read_text()

    log.debug(f"GET {url}")
    response = session.get(url)
    try:
        response.raise_for_status()

    except HTTPError as e:
        log.error(f"request failed: {e}", exc_info=e)
        log.debug(f"response: %s", response.text)
        raise

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(response.text, encoding="utf-8", errors="replace")
    return response.text


@dataclass(frozen=True)
class UEXEndpointParameter:
    name: str
    type: str
    length: int
    is_required: bool


@dataclass(frozen=True)
class UEXEndpointLink:
    link: str
    required_params: list[UEXEndpointParameter]


@dataclass(frozen=True)
class UEXEndpoint:
    id: str
    method: str
    base_path: str
    description: str
    docs_url: str
    is_user_bound: bool
    links: list[UEXEndpointLink]


class UEXEndpointDocsParser:
    defaults = {
        "id_commodity": 33,
        "id_star_system": 68,
        "id_planet": 116,
        "id_orbit": 116,
        "id_moon": 18,
        "id_city": 5,
        "id_jurisdiction": 1,
        "id_outpost": 44,
        "id_terminal": 74,
        "id_faction": 23,
        "id_space_station": 11,
        "id_category": 1,
        "id_organization": 1,
        "id_company": 1,
        "id_vehicle": 19,
        "id_parent": 169,
        "id_item": 1,
        "id_poi": 0,
        #
        "commodity_name": "GOLD",
        "commodity_code": "GOLD",
        "commodity_slug": "gold",
        #
        "terminal_name": "TDD",
        "terminal_code": "TDORI",
        "terminal_slug": "tdori",
        #
        "uuid": "a6ec85a5-feba-4239-88e4-02e1a6e521e1",
        "code": "TDORI",
        "name": "ARC",
        #
        "is_lagrange": 1,
        "is_item_manufacturer": True,
        "is_vehicle_manufacturer": True,
        #
        "id_terminal_origin": 89,
        "id_planet_origin": 59,
        "id_orbit_origin": 59,
        "id_faction_origin": 23,
        "id_star_system_origin": 19,
        "id_terminal_destination": 12,
        "id_faction_destination": 23,
        "id_planet_destination": 4,
        "id_orbit_destination": 4,
        "id_star_system_destination": 26,
        "investment": 1_000_000,
        #
        "specialization": "trading",
        "slug": "slug",
        #
        "languages": "en",
        "day_availability": "weekends",
        "time_availability": "morning",
        "username": "kronny",
        "timezone": "Europe/Prague",
        "archetypes": "strategist",
    }

    required_args_all = {
        "commodities_prices_history",
    }

    def __init__(self, url: str, content: str, get_templated_paths: bool = False):
        self.url = url
        self.get_templated_paths = get_templated_paths

        self.soup = bs4.BeautifulSoup(content, "html.parser")
        self.table = self.soup.select_one("#table-documentation")
        log.debug("parsing endpoint docs at %s", self.url)

        self.id = self.get_id()

    def __hash__(self):
        return hash((self.url, self.get_id()))

    def get_defaults(self, parameter_name: str, default=None):
        if self.get_templated_paths:
            return f"{{{parameter_name}}}"

        default_overrides = {}
        match self.get_id():
            case "categories":
                default_overrides = {
                    "type": "item",
                    "section": "other",
                }

            case "marketplace_listings":
                default_overrides = {
                    "id": "9Nor6zAazH",
                    "slug": "training-mining-and-refining-9Nor6zAazH",
                }

            case "organizations":
                default_overrides = {
                    "slug": "uexcorp",
                }

            case "terminals":
                default_overrides = {
                    "type": "commodity",
                }

            case "commodities_raw_prices":
                default_overrides = {
                    "id_terminal": "237,241",
                    "id_commodity": 45,
                }

            case "commodities_prices_history":
                default_overrides = {
                    "id_terminal": 74,
                    "id_commodity": 68,
                }

            case "vehicles_loaners":
                default_overrides = {
                    "id_vehicle": 19,
                }

            case "vehicles_purchases_prices":
                default_overrides = {
                    "id_vehicle": 19,
                    "id_terminal": 148,
                }

            case "vehicles_rentals_prices":
                default_overrides = {
                    "id_vehicle": 148,
                    "id_terminal": 150,
                }

            case _ if re.match(r"^items", self.get_id()):
                default_overrides = {
                    "id_item": 1743,
                    "id_terminal": 268,
                }

        if parameter_name in default_overrides:
            return default_overrides[parameter_name]

        return self.defaults.get(parameter_name, default)

    def get_id(self) -> str:
        match = re.match(r".*/id/([^/]*)", str(self.url))
        return match.group(1) if match else None

    def get_method(self) -> str:
        return self.table.find("th", string=re.compile(r"\s*Method\s*")).find_next_sibling("td").text.strip()

    def get_base_path(self):
        return self.soup.find("h2", class_="text-monospace").find(string=True, recursive=False).strip()

    def get_description(self):
        return self.soup.find("h4", class_="mgb-20").text.strip()

    def is_user_bound(self) -> bool:
        input_name_tags = self.table.find("th", string=re.compile(r"\s*Input\s*")) \
            .find_next_sibling("td") \
            .find_all("strong", class_="text-violet")

        for tag in input_name_tags:
            if tag.text.strip() == "secret_key":
                return True

        return False

    def get_required_parameters(self):
        input_name_tags = self.table.find("th", string=re.compile(r"\s*Input\s*")) \
            .find_next_sibling("td") \
            .find_all("strong", class_="text-red")

        yield from self.parse_parameters_from_name_tags(input_name_tags, is_required=True)

    def get_optional_parameters(self):
        input_name_tags = self.table.find("th", string=re.compile(r"\s*Input\s*")) \
            .find_next_sibling("td") \
            .find_all("strong")
        input_name_tags = list(filter(lambda tag: "text-red" not in tag.get("class", ""), input_name_tags))

        yield from self.parse_parameters_from_name_tags(input_name_tags, is_required=False)

    def parse_parameters_from_name_tags(self, input_name_tags: Sequence[bs4.Tag], **kwargs) -> Generator[UEXEndpointParameter, Any, None]:
        for input_name_tag in input_name_tags:
            parameter_name = input_name_tag.text.strip()
            if parameter_name == "secret_key":
                continue

            type_info_tag = input_name_tag.find_next_sibling("em")
            type_info = re.match(r"(?P<name>[^(]+)(\((?P<length>\d+)\))?", type_info_tag.text)
            log.debug("parsed parameter type and length from (%s) and (%s): %s", input_name_tag, type_info_tag, type_info)
            yield UEXEndpointParameter(
                name=input_name_tag.text.strip(),
                type=type_info["name"].strip(),
                length=int(type_info["length"]) if type_info["length"] else 0,
                **kwargs,
            )

    def create_method_paths_for_all_params(self) -> Iterator[UEXEndpointLink]:
        base_endpoint_path = self.get_base_path()
        required_params = set(self.get_required_parameters())
        optional_params = set(self.get_optional_parameters())

        if self.get_id() in self.required_args_all:
            required_params_x = [required_params]

        else:
            required_params_x = [
                [required_param]
                for required_param in required_params
            ]

        # ensure there is at least one request without any optional parameters
        optional_params_x = list([[], *optional_params])

        if len(required_params_x) == 0:
            log.debug("no required parameters")
            yield from self.create_method_urls_for_all_optional_params(base_endpoint_path, optional_params_x, [])

        for requireds in required_params_x:
            optional_params_x.extend(required_params.difference(requireds))
            yield from self.create_method_urls_for_all_optional_params(base_endpoint_path, optional_params_x, requireds)

    def create_method_urls_for_all_optional_params(
            self,
            base_endpoint_path,
            optional_params: Sequence[UEXEndpointParameter | Sequence[UEXEndpointParameter]],
            required_params: Sequence[UEXEndpointParameter]
    ) -> Iterator[UEXEndpointLink]:
        if len(optional_params) == 0 or self.get_templated_paths:
            log.debug("no optional parameters (or templated path generation requested: %s)", self.get_templated_paths)
            url = self.create_endpoint_url(base_endpoint_path, [], required_params)
            yield url
            # log.info("generated endpoint request URL: %s", url)

        for optionals in optional_params:
            if not isinstance(optionals, list):
                optionals = [optionals]

            url = self.create_endpoint_url(base_endpoint_path, optionals, required_params)
            yield url
            # log.info("generated endpoint request URL: %s", url)

    def create_endpoint_url(
            self,
            base_endpoint_path,
            optional_params: Sequence[UEXEndpointParameter],
            required_params: Sequence[UEXEndpointParameter]
    ) -> UEXEndpointLink:
        parameters_path = "/"
        for parameter in required_params:
            parameters_path += f"{parameter.name}/{self.get_defaults(parameter.name)}/"

        parameters_query = {}
        for parameter in optional_params:
            parameters_query[parameter.name] = self.get_defaults(parameter.name, "")

        parameters_query_str = "&".join([f"{key}={value}" for key, value in parameters_query.items()])
        if parameters_query_str:
            parameters_query_str = f"?{parameters_query_str}"

        url = f"{base_endpoint_path}{parameters_path}" if self.get_templated_paths else f"{base_endpoint_path}{parameters_path}{parameters_query_str}"
        return UEXEndpointLink(
            link=url,
            required_params=list(required_params),
        )


class DocsParser:

    def __init__(self, settings: Settings = None):
        self.settings = settings
        self.web_session = requests.Session()
        self.web_session.verify = False
        self.web_session.auth = ("supporter", "uex")

    def run(self) -> Generator[UEXEndpoint, Any, None]:
        response_data = get_from_cache_or_request(self.web_session, self.settings.docs_path, self.settings)
        soup = bs4.BeautifulSoup(response_data, "html.parser")
        endpoint_links = list(self.find_endpoint_links(soup))
        log.info("discovered %d endpoints", len(endpoint_links))
        if len(endpoint_links) == 0:
            log.error("no endpoint links found")

        for link in endpoint_links:
            try:
                yield self.process_endpoint_docs(link)

            except HTTPError:
                log.exception("failed to process endpoint %s", link)
                continue

    def process_endpoint_docs(self, link) -> UEXEndpoint:
        response_data = get_from_cache_or_request(self.web_session, link, self.settings)
        parser = UEXEndpointDocsParser(link, response_data, get_templated_paths=self.settings.get_templated_paths)
        endpoint_id = parser.get_id()
        log.info("discovered endpoint: %s %s (%s)", parser.get_method(), endpoint_id, parser.get_description())
        link_versions = parser.create_method_paths_for_all_params()
        return UEXEndpoint(
            id=endpoint_id,
            method=parser.get_method(),
            base_path=parser.get_base_path(),
            description=parser.get_description(),
            docs_url=link,
            is_user_bound=parser.is_user_bound(),
            links=list(link_versions),
        )

    @staticmethod
    def find_endpoint_links(soup: bs4.BeautifulSoup) -> Iterator[str]:
        for link_tag in soup.select("p.mgb-5.pdl-10 a"):
            yield link_tag["href"]


class APICollector:

    tag_mapping = {
        "Static": [
            "/languages",
            "/data_parameters",
            "/data_extract",
        ],
        "Game": [
            "/categories",
            "/categories_attributes",
            "/cities",
            "/companies",
            "/contacts",
            "/contracts",
            "/factions",
            "/game_versions",
            "/jump_points",
            "/jurisdictions",
            "/moons",
            re.compile(r"^/orbits.*$"),
            "/outposts",
            "/planets",
            "/poi",
            "/release_notes",
            "/space_stations",
            "/star_systems",
            re.compile(r"^/terminals.*$"),
            "/vehicles",
        ],
        "Organizations": [
            re.compile(r"^/organizations.*$"),
        ],
        "Crew": [
            re.compile(r"^/crew.*$"),
        ],
        "Commodities": [
            re.compile(r"^/commodities.*$"),
        ],
        "Fuel": [
            re.compile(r"^/fuel.*$"),
        ],
        "Marketplace": [
            re.compile(r"^/marketplace.*$"),
        ],
        "Items": [
            re.compile(r"^/items.*$"),
        ],
        "Refineries": [
            re.compile(r"^/refineries.*$"),
        ],
        "Vehicles": [
            re.compile(r"^/vehicles.*$"),
        ],
    }

    without_auth = [
        "/data_extract",
    ]

    def __init__(self, settings: Settings = None):
        self.settings = settings
        self.api_session = create_api_session()
        self.docs_parser = DocsParser(settings)

    def run(self):
        endpoints = self.docs_parser.run()
        self.collect(endpoints)

    def collect(self, all_endpoints: Sequence[UEXEndpoint]):
        for endpoint in all_endpoints:
            try:
                self.collect_endpoint(endpoint)

            except HTTPError:
                continue

    def collect_endpoint(self, endpoint):
        if endpoint.method != "GET":
            log.debug("skipping non-GET endpoint: %s", endpoint.method)
            return

        for endpoint_variant in endpoint.links:
            _ = get_from_cache_or_request(self.api_session, self.settings.base_path + endpoint_variant.link, self.settings)

    def get_tags(self, endpoint: UEXEndpoint) -> list[str]:
        tags = []
        if endpoint.is_user_bound:
            tags.append("User")

        for tag, paths in self.tag_mapping.items():
            if endpoint.base_path in paths:
                tags.append(tag)
                continue

            for path in paths:
                if isinstance(path, str) and endpoint.base_path == path:
                    tags.append(tag)
                    break

                elif isinstance(path, re.Pattern) and path.match(endpoint.base_path):
                    tags.append(tag)
                    break

        return tags

    def get_security(self, endpoint : UEXEndpoint) -> list[dict]:
        securities = []
        if endpoint.is_user_bound:
            securities.append({
                "user": {},
            })

        if endpoint.base_path not in self.without_auth:
            securities.append({
                "application": {},
            })

        return securities


class OpenAPIManager:

    schema_name_by_property_path = {
        "GetCategoriesOkResponse.properties.data.items": "CategoryDTO",
        "GetCitiesOkResponse.properties.data.items": "UniverseCityDTO",
        "GetCommoditiesAveragesOkResponse.properties.data.items": "CommodityAveragePriceDTO",
        "GetCommoditiesOkResponse.properties.data.items": "CommodityDTO",
        "GetCommoditiesPricesAllOkResponse.properties.data.items": "CommodityPriceBriefDTO",
        "GetCommoditiesPricesHistoryOkResponse.properties.data.items": "HistoricalCommodityPriceDTO",
        "GetCommoditiesPricesOkResponse.properties.data.items": "CommodityPriceDTO",
        "GetCommoditiesRankingOkResponse.properties.data.items": "CommodityRankingDTO",
        "GetCommoditiesRawPricesAllOkResponse.properties.data.items": "RawCommodityPriceBriefDTO",
        "GetCommoditiesRawPricesOkResponse.properties.data.items": "RawCommodityPriceDTO",
        "GetCommoditiesRoutesOkResponse.properties.data.items": "CommodityRouteDTO",
        "GetCommoditiesStatusOkResponse.properties.data.properties.buy.items": "CommodityStatusDTO",
        "GetCommoditiesStatusOkResponse.properties.data.properties.sell.items": "CommodityStatusDTO",
        "GetCommoditiesRawAveragesOkResponse.properties.data.properties.sell.items": "CommodityRawAverageDTO",
        "GetCompaniesOkResponse.properties.data.items": "CompanyDTO",
        "GetContactsOkResponse.properties.data.items": "ContactDTO",
        "GetContractsOkResponse.properties.data.items": "ContractDTO",
        "GetCrewOkResponse.properties.data.items": "CrewProfileDTO",
        "GetDataParametersOkResponse.properties.data": "ParametersDTO",
        "GetFactionsOkResponse.properties.data.items": "FactionDTO",
        "GetFleetOkResponse.properties.data.items": "FleetVehicleDTO",
        "GetGameVersionsOkResponse.properties.data": "GameVersionsDTO",
        "GetFuelPricesAllOkResponse.properties.data": "FuelPriceDTO",
        "GetFuelPricesOkResponse.properties.data": "FuelPriceBriefDTO",
        "GetItemsOkResponse.properties.data.items": "ItemDTO",
        "GetItemsPricesAllOkResponse.properties.data.items": "ItemPriceBriefDTO",
        "GetItemsPricesOkResponse.properties.data.items": "ItemPriceDTO",
        "GetItemsAttributesOkResponse.properties.data.items": "ItemAttributeDTO",
        "GetWalletBalanceOkResponse.properties.data.items": "WalletBalanceDTO",
        # "GetMarketplaceFavoritesOkResponse.properties.data.items": "",
        "GetMarketplaceListingsOkResponse.properties.data.items": "MarketplaceListingDTO",
        "GetJumpPointsOkResponse.properties.data.items": "JumpPointDTO",
        "GetJurisdictionsOkResponse.properties.data.items": "JurisdictionDTO",
        "GetPoiOkResponse.properties.data.items": "PointOfInterestDTO",
        "GetReleaseNotesOkResponse.properties.data.items": "ReleaseNotDTO",
        "GetMoonsOkResponse.properties.data.items": "UniverseMoonDTO",
        "GetOrbitsOkResponse.properties.data.items": "UniverseOrbitDTO",
        "GetOrganizationsOkResponse.properties.data.items": "OrganizationDTO",
        "GetOutpostsOkResponse.properties.data.items": "UniverseOutpostDTO",
        "GetPlanetsOkResponse.properties.data.items": "UniversePlanetDTO",
        "GetRefineriesAuditsOkResponse.properties.data.items": "RefineryAuditDTO",
        "GetRefineriesCapacitiesOkResponse.properties.data.items": "RefineryCapacityDTO",
        "GetRefineriesMethodsOkResponse.properties.data.items": "RefineryMethodDTO",
        "GetRefineriesYieldsOkResponse.properties.data.items": "RefineryYieldDTO",
        "GetSpaceStationsOkResponse.properties.data.items": "UniverseSpaceStationDTO",
        "GetStarSystemsOkResponse.properties.data.items": "UniverseStarSystemDTO",
        "GetTerminalsOkResponse.properties.data.items": "UniverseTerminalDTO",
        "GetUserOkResponse.properties.data": "UexUserDTO",
        "GetUserRefineriesJobsOkResponse.properties.data.items": "UserRefineryJobDTO",
        "GetUserTradesOkResponse.properties.data.items": "UserTradeDTO",
        "GetVehiclesLoanersOkResponse.properties.data": "LoanerVehicleDTO",
        "GetVehiclesOkResponse.properties.data.items": "VehicleDTO",
        "GetVehiclesPricesOkResponse.properties.data.items": "VehiclePricesDTO",
        "GetVehiclesPurchasesPricesAllOkResponse.properties.data.items": "VehiclePurchasePriceBriefDTO",
        "GetVehiclesPurchasesPricesOkResponse.properties.data.items": "VehiclePurchasePriceDTO",
        "GetVehiclesRentalsPricesAllOkResponse.properties.data.items": "VehicleRentalPriceBriefDTO",
        "GetVehiclesRentalsPricesOkResponse.properties.data.items": "VehicleRentalPriceDTO",
    }

    def __init__(self):
        self.schema = {"paths": {}}
        self.read()

    def read(self):
        with open("openapi.yaml", "r") as fd:
            self.schema = yaml.safe_load(fd) or self.schema

    def write(self):
        with open("openapi.yaml", "w") as fd:
            yaml.dump(self.schema, fd)

    def add_paths(self, paths: Sequence[str]):
        paths = list(paths)
        self.schema["x-path-templates"] = paths + self.schema["x-path-templates"]

    def update_path_data(self, data_by_path: dict[str, dict]):
        for schema_path, schema_operations in self.schema["paths"].items():
            for schema_operation, schema_operation_props in schema_operations.items():
                if schema_path in data_by_path:
                    # there are operations defined for current schema path
                    path_operation_mapping = data_by_path[schema_path]
                    if schema_operation in path_operation_mapping:
                        # data is defined for current schema path and operation
                        schema_operation_props.update(path_operation_mapping[schema_operation])

                    else:
                        log.warning(f"no data not set for %s %s", schema_operation, schema_path)

                else:
                    log.warning(f"no data mapping set for %s", schema_path)

    def deep_get_overwrite(self, d, keys: list[str], value: Any = None):
        if len(keys) == 1 and value is not None:
            d[keys[0]] = value
            return d

        elif len(keys) > 0:
            if isinstance(d, dict):
                key = keys[0]
                if key not in d:
                    d[key] = {}

                return self.deep_get_overwrite(d.get(key), keys[1:], value=value)

            else:
                raise Exception(f"expected dict, got {type(d)}")

        else:
            return d

    def overwrite_keys(self, key: str, data: dict):
        keys = key.split(".")
        source = self.deep_get_overwrite(data, keys)
        log.debug("overwriting %s with %s", key, pprint.pformat(source))
        self.deep_get_overwrite(self.schema, keys, value=source)

    def deep_equals(self, item1, item2):
        if isinstance(item1, dict) and isinstance(item2, dict):
            item2_keys = set(item2.keys())
            for key, value in item1.items():
                if key not in item2:
                    return False

                item2_keys.remove(key)
                if not self.deep_equals(value, item2[key]):
                    return False

            return len(item2_keys) == 0

        elif isinstance(item1, list) and isinstance(item2, list):
            if len(item1) != len(item2):
                return False

            for i in range(len(item1)):
                if not self.deep_equals(item1[i], item2[i]):
                    return False

            return True

        else:
            return item1 == item2

    def add_new_schema(self, name: str, schema: dict):
        if "components" not in self.schema:
            self.schema["components"] = {}

        if "schemas" not in self.schema["components"]:
            self.schema["components"]["schemas"] = {}

        if name not in self.schema["components"]["schemas"]:
            log.debug("creating new component schema %s: %s", name, schema)
            self.schema["components"]["schemas"][name] = copy.deepcopy(schema)

        else:
            existing_schema = self.schema["components"]["schemas"][name]
            if not self.deep_equals(existing_schema, schema):
                log.error(f"schema {name} already defined, but with different definition")

    def create_initial_response_schemas(self, endpoint: UEXEndpoint):
        endpoint_name = endpoint.base_path.replace("/", "_").strip("_").lower()
        path_with_operations = {
            link_template.link: self.schema["paths"].get(link_template.link, {})
            for link_template in endpoint.links
        }
        for path, operations in path_with_operations.items():
            for operation, props in operations.items():
                if "responses" not in props:
                    continue

                for response_code, response_props in props["responses"].items():
                    response_code_str = {
                        "200": "Ok",
                        "201": "Created",
                        "400": "Bad_Request",
                        "401": "Unauthorized",
                        "403": "Forbidden",
                        "404": "Not_Found",
                        "405": "Method_Not_Allowed",
                        "429": "Too_Many_Requests",
                        "500": "Internal_Server_Error",
                        "503": "Service_Unavailable",
                    }[response_code]

                    if "content" not in response_props:
                        continue

                    for content_type, content_props in response_props["content"].items():
                        if "schema" not in content_props:
                            continue

                        schema_props = content_props["schema"]
                        new_ref = stringcase.pascalcase(f"{operation.lower()}_{endpoint_name}_{response_code_str.lower()}_response")
                        self.add_new_schema(new_ref, schema_props)
                        content_props["schema"] = {
                            "$ref": f"#/components/schemas/{new_ref}",
                        }

    def extract_schemas(self):
        if "schemas" not in self.schema["components"]:
            return

        for selector, ref in self.schema_name_by_property_path.items():
            selector_items = selector.split(".")
            target_schema = selector_items[0]
            target_prop_path = selector_items[1:]
            if target_schema not in self.schema["components"]["schemas"]:
                log.warning(f"schema {target_schema} not found")
                continue

            schema = self.schema["components"]["schemas"][target_schema]
            new_schema_props = self.deep_get_overwrite(schema, target_prop_path)
            self.add_new_schema(ref, new_schema_props)
            log.debug("updating schema ref of %s to %s", target_schema, ref)
            self.deep_get_overwrite(schema, target_prop_path, value={
                "$ref": f"#/components/schemas/{ref}",
            })

    def consolidate_recursive_object_references(self):
        if "schemas" not in self.schema["components"]:
            return

        def process_schema(schema: dict):
            if "properties" in schema:
                schema_props = schema["properties"]
                for prop_name, prop_values in schema_props.items():
                    if "items" in prop_values:
                        if "$ref" not in prop_values["items"]:
                            for schema_name, schema in self.schema["components"]["schemas"].items():
                                if self.deep_equals(prop_values["items"], schema):
                                    schema_props[prop_name]["items"] = {
                                        "$ref": f"#/components/schemas/{schema_name}",
                                    }
                                    continue

                    elif "$ref" not in prop_values:
                        for schema_name, schema in self.schema["components"]["schemas"].items():
                            if self.deep_equals(prop_values, schema):
                                schema_props[prop_name] = {
                                    "$ref": f"#/components/schemas/{schema_name}",
                                }
                                continue

                        process_schema(prop_values)

        for schema in self.schema["components"]["schemas"].values():
            process_schema(schema)


class Mode(Enum):
    COLLECT = "collect"
    APPLY_TEMPLATES = "apply-path-templates"
    FIXUP = "fixup"
    MERGE = "merge"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", type=Mode)
    parser.add_argument("--no-api-cache", action="store_true", default=False)
    args = parser.parse_args()

    settings = Settings(
        api_cache=args.no_api_cache is False,
    )
    collector = APICollector(settings=settings)

    match args.mode:
        case Mode.COLLECT:
            collector.run()

        case Mode.APPLY_TEMPLATES:
            settings.get_templated_paths = True
            endpoints = collector.docs_parser.run()

            manager = OpenAPIManager()
            for endpoint in endpoints:
                link_templates = {item.link for item in endpoint.links}
                log.debug("adding templated paths: %s", link_templates)
                manager.add_paths(link_templates)

            manager.write()

        case Mode.FIXUP:
            settings.get_templated_paths = True
            endpoints = collector.docs_parser.run()

            manager = OpenAPIManager()
            data_mappings = {}
            for endpoint in endpoints:
                manager.create_initial_response_schemas(endpoint)
                for link_template in endpoint.links:
                    operation_id_suffix = ""
                    if link_template.required_params:
                        operation_id_suffix = "_by_" + "_and_".join(
                            [p.name.replace("id_", "") for p in link_template.required_params]
                        )
                    data_mappings[link_template.link] = {
                        endpoint.method.lower(): {
                            "operationId": stringcase.snakecase(f"{endpoint.method.lower()}_{endpoint.id}{operation_id_suffix}"),
                            "summary": endpoint.description,
                            "tags": collector.get_tags(endpoint),
                            "security": collector.get_security(endpoint),
                        },
                    }

            manager.update_path_data(data_mappings)
            manager.extract_schemas()
            # manager.consolidate_recursive_object_references()

            manager.write()

        case Mode.MERGE:
            attributes_to_merge = [
                "openapi",
                "info",
                "servers",
                "externalDocs",
                "tags",
                "components.securitySchemes",
            ]

            with open("openapi.base.yaml", "r") as fd:
                new_schema = yaml.safe_load(fd) or {"paths": {}}

            manager = OpenAPIManager()
            for key in attributes_to_merge:
                manager.overwrite_keys(key, new_schema)

            manager.write()
