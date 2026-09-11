from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

TestingType = Literal['Functional', 'Negative', 'Boundary', 'Navigation', 'Accessibility', 'Security', 'Recovery', 'State']
Suite = Literal['Smoke', 'Regression']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ExistingCase(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=1000)
    description: str = Field(default='', max_length=5000)
    module: str = Field(default='', max_length=200)
    steps: str = Field(default='', max_length=12000)
    expected_result: str = Field(default='', max_length=12000)
    testing_type: str = Field(default='', max_length=100)
    suite: str = Field(default='', max_length=100)
    source_file: str = Field(default='', max_length=255)
    source_sheet: str = Field(default='', max_length=100)
    source_row: int = Field(default=0, ge=0)


class ModuleInput(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    story: str = Field(default='', max_length=20000)
    success_criteria: str = Field(default='', max_length=20000)
    navigation: str = Field(default='', max_length=20000)
    confluence: str = Field(default='', max_length=40000)
    figma: str = Field(default='', max_length=40000)
    figma_url: str = Field(default='', max_length=2000)
    existing_cases: list[ExistingCase] = Field(default_factory=list, max_length=200)


class QAInput(StrictModel):
    story: str = Field(default='', max_length=20000)
    success_criteria: str = Field(default='', max_length=20000)
    modules: list[ModuleInput] = Field(default_factory=list, max_length=20)
    confluence: str = Field(default='', max_length=40000)
    figma: str = Field(default='', max_length=40000)
    navigation: str = Field(default='', max_length=20000)
    mode: Literal['offline', 'live'] = 'live'
    model: str = Field(default='', max_length=100)
    target_case_count: int = Field(default=0, ge=0, le=1000)
    explore_ui: bool = False
    target_url: str = Field(default='', max_length=2000)
    max_actions: int = Field(default=12, ge=1, le=30)
    max_repairs: int = Field(default=2, ge=0, le=2)

    @model_validator(mode='after')
    def exploration_input(self):
        if self.explore_ui and not self.target_url and not any(m.figma_url for m in self.modules):
            raise ValueError('Enter an application URL for UI exploration.')
        if self.explore_ui and self.mode != 'live':
            raise ValueError('Autonomous UI exploration requires live agents.')
        if self.modules:
            if len({m.id for m in self.modules}) != len(self.modules) or len({m.name.strip().casefold() for m in self.modules}) != len(self.modules):
                raise ValueError('Module IDs and names must be unique.')
            if any(not m.name.strip() or len(m.story.strip()) < 10 for m in self.modules):
                raise ValueError('Every module needs a name and a user story of at least 10 characters.')
            ids = [c.id for m in self.modules for c in m.existing_cases]
            if len(ids) != len(set(ids)):
                raise ValueError('Imported case IDs must be unique across modules.')
            size = sum(len(m.model_dump_json()) for m in self.modules)
            if size > 180000:
                raise ValueError('Use at most 180,000 characters of combined module content per run.')
        elif len(self.story.strip()) < 10:
            raise ValueError('Enter a module with a user story, or at least 10 story characters.')
        return self


class Requirement(StrictModel):
    id: str = Field(min_length=1)
    module: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: Literal['story', 'success_criteria', 'confluence', 'figma', 'ui']
    source_quote: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    critical: bool
    required_types: list[TestingType] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Requirements(StrictModel):
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    questions: list[str] = Field(default_factory=list)


class Edge(StrictModel):
    id: str = Field(min_length=1)
    module: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    action: str = Field(min_length=1)
    condition: str
    evidence_ids: list[str] = Field(default_factory=list)


class Journey(StrictModel):
    id: str
    name: str
    module: str
    edge_ids: list[str] = Field(min_length=1)
    critical: bool


class Navigation(StrictModel):
    edges: list[Edge] = Field(max_length=100)
    journeys: list[Journey] = Field(max_length=40)
    questions: list[str] = Field(default_factory=list)


class Step(StrictModel):
    action: str = Field(min_length=3)
    expected_result: str = Field(min_length=3)


class Case(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=5)
    description: str = Field(min_length=10)
    module: str = Field(min_length=1)
    suite: Suite
    testing_type: TestingType
    priority: Literal['P0', 'P1', 'P2', 'P3']
    level: Literal['E2E', 'Module', 'Integration']
    role: str = Field(min_length=1)
    preconditions: list[str] = Field(min_length=1)
    test_data: list[str] = Field(min_length=1)
    steps: list[Step] = Field(min_length=1, max_length=40)
    expected_result: str = Field(min_length=3)
    requirement_ids: list[str]
    edge_ids: list[str]
    journey_ids: list[str]
    evidence_ids: list[str]
    assumptions: list[str]
    status: Literal['Draft', 'Needs clarification'] = 'Draft'
    origin: Literal['New', 'Improved'] = 'New'
    existing_case_ids: list[str] = Field(default_factory=list)


class Cases(StrictModel):
    cases: list[Case] = Field(max_length=120)


class Finding(StrictModel):
    id: str
    severity: Literal['Critical', 'Major', 'Minor']
    owner: Literal['Requirements analyst', 'Figma explorer', 'Smoke designer', 'Regression designer', 'Product owner']
    description: str = Field(min_length=3)
    target_ids: list[str]


class ExistingCaseReview(StrictModel):
    existing_case_id: str
    disposition: Literal['Reuse', 'Improve', 'Duplicate', 'Obsolete', 'Needs clarification']
    reason: str = Field(min_length=5)


class Review(StrictModel):
    findings: list[Finding] = Field(max_length=100)
    decision: str = Field(min_length=3)
    existing_case_reviews: list[ExistingCaseReview] = Field(default_factory=list, max_length=200)


class BrowserDecision(StrictModel):
    action: Literal['click', 'back', 'stop']
    ref: str = ''
    reason: str = Field(min_length=3)


class ModuleStrategy(StrictModel):
    module: str
    priority: Literal['P0', 'P1', 'P2', 'P3']
    test_focus: list[str] = Field(min_length=1)
    estimated_case_count: int = Field(ge=1, le=1000)


class Strategy(StrictModel):
    modules: list[ModuleStrategy]
    decisions: list[str]
    gaps: list[str]


class TestPlan(StrictModel):
    title: str
    overview: str
    scope_in: list[str] = Field(min_length=1)
    scope_out: list[str] = Field(min_length=1)
    approach: list[str] = Field(min_length=1)
    environments: list[str] = Field(min_length=1)
    entry_criteria: list[str] = Field(min_length=1)
    exit_criteria: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    deliverables: list[str] = Field(min_length=1)
    assumptions: list[str]
    case_ids: list[str]
