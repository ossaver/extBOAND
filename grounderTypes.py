from dataclasses import dataclass, field
from enum import IntEnum

BOOL_FALSE = 0
BOOL_TRUE = 1

class TermType(IntEnum):
    TERM_CONSTANT = 0
    TERM_PARAMETER = 1
    TERM_CONTROL_VAR = 2

class Comparator(IntEnum):
    CMP_EQ = 0
    CMP_LESS = 1
    CMP_LESS_EQ = 2
    CMP_GREATER = 3
    CMP_GREATER_EQ = 4
    CMP_NEQ = 5
    CMP_DUMMY = 6


class GroundedNumericExpressionType(IntEnum):
    GE_NUMBER = 0
    GE_VAR = 1
    GE_SUM = 2
    GE_SUB = 3
    GE_DIV = 4
    GE_MUL = 5
    GE_OBJECT = 6
    GE_DURATION = 7
    GE_SHARP_T = 8
    GE_CONTROL_VAR = 9
    GE_UNDEFINED = 10


class Assignment(IntEnum):
    AS_ASSIGN = 0
    AS_INCREASE = 1
    AS_DECREASE = 2
    AS_SCALE_UP = 3
    AS_SCALE_DOWN = 4

class MetricExpressionType(IntEnum):
    MT_PLUS = 0
    MT_MINUS = 1
    MT_PROD = 2
    MT_DIV = 3
    MT_NUMBER = 4
    MT_TOTAL_TIME = 5
    MT_IS_VIOLATED = 6
    MT_FLUENT = 7
    
# Handles numeric expr to str.
def _numeric_expr_to_str(expr, grounder):
    t = expr.type

    # Formats a numeric expression parameter for display.
    def render_param(p):
        if isinstance(p, int):
            if grounder is None:
                return str(p)
            return getattr(grounder.objects[p], "name", str(p))
        return str(p)

    if t == GroundedNumericExpressionType.GE_NUMBER:
        return str(expr.value)

    if t == GroundedNumericExpressionType.GE_VAR:
        if grounder is None:
            return f"var_{expr.index}"
        v = grounder.gTask.variables[expr.index]
        params = [render_param(p) for p in v.params]
        return grounder.getVariableName(v.fncIndex, params)

    if t == GroundedNumericExpressionType.GE_OBJECT:
        if grounder is None:
            return str(expr.index)
        return getattr(grounder.objects[expr.index], "name", str(expr.index))

    if t in {
        GroundedNumericExpressionType.GE_SUM,
        GroundedNumericExpressionType.GE_SUB,
        GroundedNumericExpressionType.GE_MUL,
        GroundedNumericExpressionType.GE_DIV,
    }:
        op = {
            GroundedNumericExpressionType.GE_SUM: "+",
            GroundedNumericExpressionType.GE_SUB: "-",
            GroundedNumericExpressionType.GE_MUL: "*",
            GroundedNumericExpressionType.GE_DIV: "/",
        }[t]

        return f"({op} {' '.join(_numeric_expr_to_str(x, grounder) for x in expr.terms)})"

    if t == GroundedNumericExpressionType.GE_DURATION:
        return "#t"

    if t == GroundedNumericExpressionType.GE_CONTROL_VAR:
        return f"cv_{expr.index}"

    return "UNDEFINED"
    
@dataclass
class Term:
    type: TermType
    index: int

    # Compares this object with another internal representation.
    def equals(self, other):
        return self.type == other.type and self.index == other.index

@dataclass
class GroundedValue:
    time: float = 0.0
    value: int = 0
    numericValue: float = 0.0


@dataclass
class GroundedVar:
    index: int
    fncIndex: object
    params: list
    isNumeric: bool
    initialValues: list = field(default_factory=list)

@dataclass
class GrounderAssignment:
    fncIndex: object
    params: list
    value: Term
    grounded: bool = False

    # Builds a grounded condition from an operator fluent.
    @classmethod
    def from_opfluent(cls, f):
        return cls(
            fncIndex=f.variable.fncIndex,
            params=f.variable.params,
            value=f.value,
            grounded=False,
        )
    
@dataclass
class Literal:
    fncIndex: object
    params: list = field(default_factory=list)

    # Compares this object with another internal representation.
    def equals(self, l):
        if self.fncIndex != l.fncIndex:
            return False
        if len(self.params) != len(l.params):
            return False
        for i in range(len(self.params)):
            if not self.params[i].equals(l.params[i]):
                return False
        return True
    
@dataclass
class OpFluent:
    variable: Literal
    value: Term

    # Formats a grounded value name using parameter values.
    def getValueName(self, paramValues):
        if self.value.type == TermType.TERM_PARAMETER:
            if paramValues[self.value.index] == None:
                return "?" + str(self.value.index)
            return str(paramValues[self.value.index])
        return str(self.value.index)
    
@dataclass
class ProgrammedValue:
    index: int
    varIndex: int
    valueIndex: int

@dataclass
class SyntheticOperator:
    name: str
    parameters: list = field(default_factory=list)
    precondition: object = None
    effect: object = None
    instantaneous: bool = True
    isTIL: bool = False
    isGoal: bool = False
    equality: list = field(default_factory=list)

@dataclass
class OpEquality:
    value1: Term
    value2: Term
    equal: bool
    
@dataclass
class GrounderOperator:
    index: int = -1
    op: object = None
    numParams: int = 0
    paramValues: list = field(default_factory=list)
    compatibleObjectsWithParam: list = field(default_factory=list)
    newValueIndex: int = 0
    preconditions: list = field(default_factory=list)
    numericPreconditions: list = field(default_factory=list)
    effects: list = field(default_factory=list)
    numericEffects: list = field(default_factory=list)
    equality: list = field(default_factory=list)

    # Initializes a grounded action from grounded preconditions and effects.
    def initialize(self, action, preconditions, numericPreconditions, effects, numericEffects, equality=None):
        self.op = action
        self.numParams = len(action.parameters)
        self.paramValues = [[] for _ in range(self.numParams)]
        self.compatibleObjectsWithParam = [[] for _ in range(self.numParams)]
        self.preconditions = [GrounderAssignment.from_opfluent(p) for p in preconditions]
        self.numericPreconditions = list(numericPreconditions)
        self.effects = list(effects)
        self.numericEffects = list(numericEffects)
        self.equality = list(equality or [])
        
@dataclass
class GroundedCondition:
    varIndex: int
    valueIndex: int
    
@dataclass
class GroundedNumericExpression:
    type: GroundedNumericExpressionType
    value: float = 0.0
    index: int = 0
    terms: list = field(default_factory=list)
    variable: object = None   # NumericVariableRef o None
    
@dataclass
class GroundedNumericCondition:
    comparator: Comparator
    terms: list = field(default_factory=list)  # list[GroundedNumericExpression]

@dataclass
class GroundedNumericEffect:
    assignment: Assignment
    varIndex: int = -1
    exp: GroundedNumericExpression = None
    variable: object = None   # NumericVariableRef o None
    
@dataclass
class GroundedAction:
    index: int = 0
    name: str = ""
    parameters: list = field(default_factory=list)

    conditions: list = field(default_factory=list)          # list[GroundedCondition]
    numericConditions: list = field(default_factory=list)   # list[GroundedNumericCondition]

    effects: list = field(default_factory=list)             # list[GroundedCondition]
    numericEffects: list = field(default_factory=list)      # list[GroundedNumericEffect]

    instantaneous: bool = True
    isTIL: bool = False
    isGoal: bool = False
    
    # Returns the readable string representation.
    def __str__(self):
        return self.to_string()
    
    # Formats the object for readable output.
    def to_string(self, grounder=None):
        # Formats an object index for nested output rendering.
        def obj_name(idx):
            if grounder is None:
                return str(idx)
            obj = grounder.objects[idx]
            return getattr(obj, "name", str(obj))
    
        # Formats a variable index for nested output rendering.
        def var_name(varIndex):
            if grounder is None:
                return f"var_{varIndex}"
            v = grounder.gTask.variables[varIndex]
            params = [obj_name(p) for p in v.params]
            return grounder.getVariableName(v.fncIndex, params)
    
        # Formats a condition value for nested output rendering.
        def cond_value_name(varIndex, valueIndex):
            if valueIndex == BOOL_TRUE:
                return "true"
            if valueIndex == BOOL_FALSE:
                return "false"
    
            if grounder is None:
                return str(valueIndex)
    
            return obj_name(valueIndex)
    
        lines = []
    
        if grounder is not None:
            params = [obj_name(p) for p in self.parameters]
        else:
            params = [str(p) for p in self.parameters]
    
        lines.append(f"Action: {self.name}({', '.join(params)})")
    
        lines.append("  Preconditions:")
        for c in self.conditions:
            vname = var_name(c.varIndex)
            value = cond_value_name(c.varIndex, c.valueIndex)
            lines.append(f"    {vname} = {value}")
    
        for c in self.numericConditions:
            terms = [_numeric_expr_to_str(t, grounder) for t in c.terms]
            lines.append(f"    ({c.comparator.name} {' '.join(terms)})")
    
        lines.append("  Effects:")
        for e in self.effects:
            vname = var_name(e.varIndex)
            value = cond_value_name(e.varIndex, e.valueIndex)
            lines.append(f"    {vname} := {value}")
    
        for e in self.numericEffects:
            lhs = var_name(e.varIndex)
            exp = _numeric_expr_to_str(e.exp, grounder)
            lines.append(f"    ({e.assignment.name} {lhs} {exp})")
    
        return "\n".join(lines)

@dataclass
class NumericVariableRef:
    fncIndex: object
    params: list = field(default_factory=list)   # lista de Term
    
@dataclass
class GroundedMetric:
    type: MetricExpressionType
    value: float = 0.0
    index: int = 0
    terms: list = field(default_factory=list)   # list[GroundedMetric]
    
@dataclass
class GroundedTask:
    variables: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    goals: list = field(default_factory=list)
    reachedValues: list = field(default_factory=list)
    metric: GroundedMetric = None
    metricType: str = "X"
    
    # Formats the object for readable output.
    def to_string(self, grounder=None):
        # Formats an object index for nested output rendering.
        def obj_name(idx):
            if grounder is None:
                return str(idx)
            obj = grounder.objects[idx]
            return getattr(obj, "name", str(obj))
    
        # Formats a variable index for nested output rendering.
        def var_name(v):
            if grounder is None:
                return f"var_{v.index}"
            params = [obj_name(p) for p in v.params]
            return grounder.getVariableName(v.fncIndex, params)
    
        # Formats an initial value for nested task rendering.
        def initial_value_str(v):
            # Numéricas
            if v.isNumeric:
                if len(v.initialValues) == 0:
                    return "undefined"
                return str(v.initialValues[0].numericValue)
        
            # No numéricas:
            # en esta traducción, ausencia de hecho inicial => false para proposicionales
            if len(v.initialValues) == 0:
                return "false"
        
            iv = v.initialValues[0]
        
            if iv.value == BOOL_TRUE:
                return "true"
            if iv.value == BOOL_FALSE:
                return "false"
        
            return obj_name(iv.value)
    
        # Formats a metric expression for nested task rendering.
        def metric_to_str(m):
            if m is None:
                return ""
    
            if m.type == MetricExpressionType.MT_NUMBER:
                return str(m.value)
    
            if m.type == MetricExpressionType.MT_FLUENT:
                v = self.variables[m.index]
                return var_name(v)
    
            if m.type in {
                MetricExpressionType.MT_PLUS,
                MetricExpressionType.MT_MINUS,
                MetricExpressionType.MT_PROD,
                MetricExpressionType.MT_DIV,
            }:
                op = {
                    MetricExpressionType.MT_PLUS: "+",
                    MetricExpressionType.MT_MINUS: "-",
                    MetricExpressionType.MT_PROD: "*",
                    MetricExpressionType.MT_DIV: "/",
                }[m.type]
    
                return f"({op} {' '.join(metric_to_str(x) for x in m.terms)})"
    
            return "UNKNOWN_METRIC"
    
        lines = []
    
        # VARIABLES
        lines.append("Variables:")
        for v in self.variables:
            lines.append(f"  {var_name(v)} = {initial_value_str(v)}")
    
        # ACTIONS
        lines.append("\nActions:")
        for a in self.actions:
            lines.append(a.to_string(grounder))
            lines.append("")
    
        # GOALS
        lines.append("\nGoals:")
        for g in self.goals:
            lines.append(g.to_string(grounder))
            lines.append("")
    
        # METRIC
        lines.append("\nMetric:")
        if self.metricType == "X" or self.metric is None:
            lines.append("  None")
        else:
            direction = "maximize" if self.metricType == ">" else "minimize"
            lines.append(f"  {direction} {metric_to_str(self.metric)}")
    
        return "\n".join(lines)