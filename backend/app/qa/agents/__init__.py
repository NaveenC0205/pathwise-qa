from .requirements import agent as requirements
from .figma_explorer import agent as figma_explorer
from .smoke import agent as smoke
from .regression import agent as regression
from .reviewer import agent as reviewer
from .browser_decision import agent as browser_decision
from .supervisor import agent as supervisor
from .test_plan import agent as test_plan

AGENTS = {'Requirements analyst': requirements, 'Figma explorer': figma_explorer, 'Smoke designer': smoke, 'Regression designer': regression, 'Coverage reviewer': reviewer, 'Browser decision': browser_decision, 'QA supervisor': supervisor, 'Test plan writer': test_plan}
