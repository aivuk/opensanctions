from zavod.meta import get_catalog, load_dataset_from_path, Dataset
from zavod.tools.meta_index import export_index
from ..conftest import FIXTURES_PATH
from zavod.context import Context
from zavod import settings
from json import load
from zavod.runner import run_dataset
from zavod.exporters import export

COLLECTION_YML = FIXTURES_PATH / "collection.yml"


def test_export_index(vdataset: Dataset):
    # Create dataset index files
    context1 = Context(vdataset)
    run_dataset(vdataset)
    export(vdataset.name)

    dataset2 = load_dataset_from_path(DATASET_2_YML)
    run_dataset(dataset2)
    export(dataset2.name)

    # Clear catalog as if this is a fresh process separate from the earlier exports
    get_catalog.cache_clear()

    collection = load_dataset_from_path(COLLECTION_YML)
    export(collection.name)
    export_index(collection)

    with open(settings.DATA_PATH / "datasets" / "index.json") as index_file:
        index = load(index_file)
        datasets = {r["name"] for r in index["datasets"]}
        assert "testdataset1" in datasets
        assert "testdataset2" in datasets
