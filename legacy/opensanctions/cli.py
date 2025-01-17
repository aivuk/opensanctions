import sys
import click
import logging
from pathlib import Path
from nomenklatura.judgement import Judgement
from nomenklatura.resolver import Identifier
from followthemoney.cli.util import OutPath

from zavod.logs import get_logger, configure_logging
from zavod.crawl import crawl_dataset
from zavod.dedupe import get_resolver
from zavod.tools.dump_file import dump_dataset_to_file
from zavod.tools.meta_index import export_index
from zavod.exc import RunFailedException
from opensanctions.core.catalog import get_catalog, get_dataset_names
from opensanctions.core.training import export_training_pairs
from zavod.exporters import export
from zavod.util import write_json

log = get_logger(__name__)
datasets = click.Choice(get_dataset_names())
ALL_SCOPE = "all"
DEFAULT_SCOPE = "default"


@click.group(help="OpenSanctions ETL toolkit")
@click.option("-v", "--verbose", is_flag=True, default=False)
@click.option("-q", "--quiet", is_flag=True, default=False)
def cli(verbose=False, quiet=False):
    level = logging.INFO
    if quiet:
        level = logging.WARNING
    if verbose:
        level = logging.DEBUG
    configure_logging(level=level)
    get_catalog()


@cli.command("crawl", help="Crawl entities into the given dataset")
@click.argument("dataset", default=ALL_SCOPE, type=datasets)
@click.option("-d", "--dry-run", is_flag=True, default=False)
def crawl(dataset: str, dry_run: bool):
    """Crawl all datasets within the given scope."""
    scope = get_catalog().require(dataset)
    failed = False
    for source in scope.leaves:
        try:
            crawl_dataset(source, dry_run=dry_run)
        except RunFailedException:
            failed = True
    if failed:
        sys.exit(1)


@cli.command("export", help="Export entities from the given dataset")
@click.argument("dataset", default=ALL_SCOPE, type=datasets)
@click.option("-r", "--recurse", is_flag=True, default=False)
def export_(dataset: str, recurse: bool = False):
    export(dataset, recurse=recurse)


@cli.command("export-index", help="Export global dataset index")
@click.argument("dataset", default=ALL_SCOPE, type=datasets)
def export_metadata_(dataset: str):
    dataset_ = get_catalog().require(dataset)
    export_index(dataset_)


@cli.command("export-pairs", help="Export pairwise judgements")
@click.argument("dataset", default=DEFAULT_SCOPE, type=datasets)
@click.option("-o", "--outfile", type=click.File("wb"), default="-")
def export_pairs(dataset, outfile):
    dataset = get_catalog().require(dataset)
    for obj in export_training_pairs(dataset):
        write_json(obj, outfile)


@cli.command("explode", help="Destroy a cluster of deduplication matches")
@click.argument("canonical_id", type=str)
def explode(canonical_id):
    resolver = get_resolver()
    resolved_id = resolver.get_canonical(canonical_id)
    for entity_id in resolver.explode(resolved_id):
        log.info("Restore separate entity", entity=entity_id)
    resolver.save()


@cli.command("merge", help="Merge multiple entities as duplicates")
@click.argument("entity_ids", type=str, nargs=-1)
@click.option("-f", "--force", is_flag=True, default=False)
def merge(entity_ids, force: bool = False):
    if len(entity_ids) < 2:
        return
    resolver = get_resolver()
    canonical_id = resolver.get_canonical(entity_ids[0])
    for other_id in entity_ids[1:]:
        other_id = Identifier.get(other_id)
        other_canonical_id = resolver.get_canonical(other_id)
        if other_canonical_id == canonical_id:
            continue
        check = resolver.check_candidate(canonical_id, other_id)
        if not check:
            edge = resolver.get_resolved_edge(canonical_id, other_id)
            if force is True:
                if edge is not None:
                    log.warn("Removing existing edge", edge=edge)
                    resolver._remove_edge(edge)
            else:
                log.error(
                    "Cannot merge",
                    canonical_id=canonical_id,
                    other_id=other_id,
                    edge=edge,
                )
                return
        log.info("Merge: %s -> %s" % (other_id, canonical_id))
        canonical_id = resolver.decide(canonical_id, other_id, Judgement.POSITIVE)
    resolver.save()
    log.info("Canonical: %s" % canonical_id)


@cli.command("export-statements", help="Export statement data as a CSV file")
@click.option("-d", "--dataset", default=ALL_SCOPE, type=datasets)
@click.option("-x", "--external", is_flag=True, default=False)
@click.argument("outfile", type=OutPath)
def export_statements_csv(outfile: Path, dataset: str, external: bool = False):
    dataset_ = get_catalog().require(dataset)
    dump_dataset_to_file(dataset_, outfile, format="csv", external=external)


if __name__ == "__main__":
    cli()
