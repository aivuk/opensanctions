from urllib.parse import urljoin, urlencode
from normality import stringify, collapse_spaces, slugify

from opensanctions.core import Context
from opensanctions import helpers as h
import re

CACHE_DAYS = 14
COUNTRY = "md"


# 11 fost președinte = former president
# 12 fost consilier = former councillor
# 14 fost asociat = former associate
# 16 asociat unic = sole associate
# 16 fost membru = former member
# 20 beneficiar 100% =
# 21 membră = member
# 26 beneficiar = beneficiary
# 27 None
# 27 acționar = shareholder
# 32 președinte = president
# 39 asociat = associate
# 52 fondator = founder (owner)
# 70 membru = member

relationships = dict()

def parse_date(text):
    return h.parse_date(text, ["%d.%m.%Y"])


def crawl_entity(context: Context, relative_url: str, follow_relations: bool = True):
    url = urljoin(context.source.data.url, relative_url)
    doc = context.fetch_html(url, cache_days=CACHE_DAYS)
    name_el = doc.find('.//span[@class="name"]')
    name = collapse_spaces(name_el.text)
    attributes = dict()
    for el in name_el.find("./..").getnext().getchildren():
        text = collapse_spaces(el.text_content())
        parts = text.split(": ")
        if len(parts) == 2:
            attributes[slugify(parts[0])] = collapse_spaces(parts[1])

    if relative_url.startswith("profile.php"):
        type_el = name_el.getnext().getnext()
    elif relative_url.startswith("connection.php"):
        type_el = None
    else:
        context.log.warn("Don't know how to handle url", url=relative_url)

    if hasattr(type_el, "text"):
        type_str = collapse_spaces(type_el.text)
    else:
        type_str = None

    entity_type = context.lookup("entity_type", type_str)
    if entity_type is None:
        entity_type = context.lookup("entity_type_by_name", name)

    entity = None
    if entity_type is None:
        entity = make_entity(context, url, name, attributes)
    elif entity_type.value == "person":
        entity = make_person(context, url, name, type_str, attributes)
    elif entity_type.value == "company":
        entity = make_company(context, url, name, attributes)
    else:
        context.log.warn("Unhandled entity type", url, type_str)

    if follow_relations and entity is not None:
        for connection in doc.findall('.//div[@class="con"]'):
            related_entity_el = connection.find("./div[2]/div[1]/span/*[1]")
            related_entity_link = related_entity_el.getparent().find(".//a")
            relationship_el = connection.find("./div/div[2]")
            if relationship_el is None:
                description = None
            else:
                description = collapse_spaces(relationship_el.text_content())
            target_name = collapse_spaces(related_entity_el.text_content())
            if related_entity_link is None:
                target_url = None
            else:
                target_url = related_entity_link.get("href")
            make_relation(context, entity, description, target_name, target_url)
    
    return entity


def make_person(
    context: Context, url: str, name: str, position: str | None, attributes: dict
):
    person = context.make("Person")
    identification = [COUNTRY, name]
    person.add("sourceUrl", url)
    person.add("name", name)
    person.add("position", position, lang="ron")

    if "data-nasterii" in attributes:
        dob = parse_date(attributes.pop("data-nasterii"))
        identification.append(dob)
        person.add("birthDate", dob)

    person.add("birthPlace", attributes.pop("locul-nasterii", None), lang="ron")
    person.add("nationality", attributes.pop("cetatenie", "").split(","))

    if attributes:
        context.log.info(f"More info to be added to {name}", attributes, url)
    person.id = context.make_id(*identification)
    person.add("topics", "poi")
    return person


def make_company(context: Context, url: str, name: str, attributes: dict):
    company = context.make("Company")
    identification = [COUNTRY, name]
    company.add("sourceUrl", url)
    company.add("name", name)
    if "data-inregistrarii" in attributes:
        founded = parse_date(attributes.pop("data-inregistrarii"))
        identification.append(founded)
        company.add("incorporationDate", founded)

    country = attributes.pop("tara", "").split(",")[0]
    company.add("mainCountry", country)

    if "numar-de-identificare" in attributes:
        regno = attributes.pop("numar-de-identificare")
        identification.append(regno)
        company.add("registrationNumber", regno)
    if attributes:
        context.log.info(f"More info to be added to {name}", attributes, url)
    company.id = context.make_id(*identification)
    return company


def make_entity(context: Context, url: str, name: str, attributes: dict):
    entity = context.make("LegalEntity")
    identification = [COUNTRY, name]
    entity.add("sourceUrl", url)
    entity.add("name", name)
    if name.startswith("Partidul"):
        entity.add("topics", "pol.party")

    if "data-fondarii" in attributes:
        founded = parse_date(attributes.pop("data-fondarii"))
        identification.append(founded)
        entity.add("incorporationDate", founded)

    entity.add("mainCountry", attributes.pop("tara", "").split(",")[0])

    if "adresa" in attributes:
        entity.add("address", h.make_address(context, full=attributes.pop("adresa")))
    if "idno" in attributes:
        regno = attributes.pop("idno")
        identification.append(regno)
        entity.add("registrationNumber", regno)
    if attributes:
        context.log.info(f"More info to be added to {name}", attributes, url)
    entity.id = context.make_id(*identification)
    return entity


def make_relation(context, source, description, target_name, target_url):
    target = None
    if target_url:
        target = crawl_entity(context, target_url, False)
        if target_url.startswith("connection.php"):
            context.emit(target)
    if target is None:
        target = context.make("LegalEntity")
        target.id = context.make_id(target_name, "relation of", source.id)
        target.add("name", target_name)
        context.emit(target)

    res = context.lookup("relations", description)
    if res:
        relation = context.make(res.schema)
        relation.id = context.make_id(target.id, "related to", source.id)
        relation.add(res.source, source.id)
        relation.add(res.target, target.id)
        relation.add(res.text, description, lang="ron")
        context.emit(relation)
    else:
        context.log.warn(
            f"Don't know how to make relationship '{description}'",
            source=source.get("sourceUrl"),
            target=target_name,
        )
        count = relationships.get(description, 0) + 1
        relationships[description] = count


def crawl(context: Context):
    query = {"br": 0, "lang": "rom"}
    while True:
        context.log.debug("Crawling index offset ", query)
        url = f"{ context.source.data.url }?{ urlencode(query) }"
        doc = context.fetch_html(url)
        profiles = doc.findall('.//div[@class="profileWindow"]//a')

        # check absurd offset just in case there are always results for some reason
        if not profiles or query["br"] > 10000:
            break

        for link in profiles:
            entity = crawl_entity(context, link.get("href"))
            if entity:
                context.emit(entity, target=True)

        query["br"] = query["br"] + len(profiles)

    for count, description in sorted([(count, description) for description, count in relationships.items()]):
        context.log.debug(count, description)
