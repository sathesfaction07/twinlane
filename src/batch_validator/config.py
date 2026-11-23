from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SelectorConfig:
    login_url: str = ""
    search_input: str = ""
    search_button: str = ""
    result_table: str = ""
    status_cell: str = ""
    image_container: str = ""
    annotation_field: str = ""
    comment_box: str = ""
    submit_button: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> "SelectorConfig":
        if not path.exists():
            return cls()
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PipelineConfig:
    input_path: Path = Path("input.csv")
    output_path: Path = Path("output/")
    selectors_path: Path = Path("config/selectors.yaml")
    max_concurrent: int = 5
    checkpoint_dir: Path = Path(".checkpoints")
    timeout_ms: int = 30000
    headless: bool = True
    retries: int = 2
    vlm_fallback: bool = False
    excel: bool = False

    selectors: SelectorConfig = field(default_factory=SelectorConfig)

    def __post_init__(self):
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.selectors = SelectorConfig.from_yaml(self.selectors_path)
