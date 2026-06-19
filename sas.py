from dataclasses import dataclass, field

from grounderTypes import (
    Assignment,
    BOOL_FALSE,
    BOOL_TRUE,
    Comparator,
    GroundedNumericExpressionType,
)


SAS_FALSE = "__false__"
SAS_TRUE = "__true__"
SAS_NONE = "__none_of_those__"


@dataclass(frozen=True)
class SASCondition:
    var: int
    value: int


@dataclass
class SASVariable:
    index: int
    name: str
    values: list = field(default_factory=list)
    initial_value: int = 0


@dataclass
class SASTranslatedAction:
    index: int
    name: str
    parameters: tuple = field(default_factory=tuple)
    conditions: tuple = field(default_factory=tuple)
    numeric_conditions: tuple = field(default_factory=tuple)
    effects: tuple = field(default_factory=tuple)
    numeric_effects: tuple = field(default_factory=tuple)
    original_action: object = None
    is_goal: bool = False
    is_fictitious: bool = False
    budget_cost: float = 0.0
    utility_loss: float = 0.0


@dataclass
class SASTask:
    variables: list = field(default_factory=list)
    numeric_variables: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    goals: list = field(default_factory=list)
    initial_state: tuple = field(default_factory=tuple)
    numeric_initial_state: tuple = field(default_factory=tuple)
    literal_to_sas: dict = field(default_factory=dict)
    sas_to_literal: dict = field(default_factory=dict)
    numeric_var_to_pos: dict = field(default_factory=dict)
    mutex_literals: set = field(default_factory=set)
    utility_by_literal: dict = field(default_factory=dict)
    utility_by_sas_value: dict = field(default_factory=dict)
    soft_goal_closure_vars: list = field(default_factory=list)
    max_utility: float = 0.0
    soft_goals_compiled: bool = False

    # Builds a SAS state tuple from a propositional state.
    def state_from_propositional_state(self, state):
        true_props, numeric_values = state
        sas_values = [_default_missing_value(var) for var in self.variables]
        seen = set()

        for literal in true_props:
            mapping = self.literal_to_sas.get(literal)
            if mapping is None:
                continue
            sas_var, sas_value = mapping
            if sas_var in seen and sas_values[sas_var] != sas_value:
                raise ValueError(
                    "State contains two true literals mapped to the same SAS variable."
                )
            sas_values[sas_var] = sas_value
            seen.add(sas_var)

        for var, value in enumerate(sas_values):
            if value is None:
                raise ValueError(
                    f"No true literal found for SAS variable {var}, "
                    "and it has no false/none fallback value."
                )

        return tuple(sas_values), tuple(numeric_values)

    # Computes the utility currently achieved by a SAS state.
    def utility_of_sas_state(self, sas_state):
        return sum(
            self.utility_by_sas_value.get((var, value), 0.0)
            for var, value in enumerate(sas_state)
        )

    # Checks whether an action can be applied in a SAS and numeric state.
    def is_action_applicable(self, sas_state, numeric_state, action):
        return (
            _check_sas_conditions(sas_state, action.conditions)
            and _check_numeric_conditions(
                numeric_state,
                action.numeric_conditions,
                self,
            )
        )

    # Applies a translated action to a SAS and numeric state.
    def apply_action(self, sas_state, numeric_state, action):
        next_sas_state = list(sas_state)
        next_numeric_state = list(numeric_state)

        for effect in action.effects:
            next_sas_state[effect.var] = effect.value

        for effect in action.numeric_effects:
            _apply_numeric_effect(next_numeric_state, numeric_state, effect, self)

        return tuple(next_sas_state), tuple(next_numeric_state)

    # Checks whether a SAS and numeric state satisfies a goal.
    def is_goal_state(self, sas_state, numeric_state, goal=None):
        if goal is None:
            return any(
                self.is_goal_state(sas_state, numeric_state, candidate)
                for candidate in self.goals
            )
        return (
            _check_sas_conditions(sas_state, goal.conditions)
            and _check_numeric_conditions(
                numeric_state,
                goal.numeric_conditions,
                self,
            )
        )

    # Checks propositional SAS conditions against a state.
    def conditions_hold(self, sas_state, conditions):
        return _check_sas_conditions(sas_state, conditions)

    # Checks numeric goal or action conditions against a state.
    def numeric_conditions_hold(self, numeric_state, conditions):
        return _check_numeric_conditions(numeric_state, conditions, self)

    # Creates the hashable state key used by caches and policies.
    def state_key(self, sas_state, numeric_state):
        return tuple(sas_state), tuple(numeric_state)

    # Formats the SAS task for debugging output.
    def to_string(self):
        lines = ["SAS variables:"]
        for var in self.variables:
            rendered_values = ", ".join(
                f"{i}:{value}" for i, value in enumerate(var.values)
            )
            lines.append(
                f"  {var.index}: {var.name} = {var.initial_value} "
                f"[{rendered_values}]"
            )

        lines.append("")
        lines.append("Numeric variables:")
        for var in self.numeric_variables:
            lines.append(f"  {var.index}: {var.fncIndex}")

        lines.append("")
        lines.append("Actions:")
        for action in self.actions:
            extra = ""
            if action.is_fictitious or action.utility_loss:
                extra = f" loss={action.utility_loss}"
            lines.append(
                f"  {action.index}: {action.name} "
                f"pre={list(action.conditions)} eff={list(action.effects)}"
                f"{extra}"
            )

        if self.utility_by_sas_value:
            lines.append("")
            lines.append("Utilities:")
            for key, value in sorted(self.utility_by_sas_value.items()):
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)


# Translates the grounded planning task into the reduced SAS representation.
def translate(task, grounder=None, utility_assignments=None):
    translator = _SASTranslator(task, grounder, utility_assignments)
    return translator.translate()


# Adds closure variables and fictitious actions for utility-bearing soft goals.
def compile_soft_goals(sas_task):
    if sas_task.soft_goals_compiled:
        return sas_task

    utility_vars = _get_utility_vars(sas_task)
    sas_task.max_utility = sum(
        max(
            sas_task.utility_by_sas_value.get((var_index, value_index), 0.0)
            for value_index in range(len(sas_task.variables[var_index].values))
        )
        for var_index in utility_vars
    )

    closure_conditions = []
    for var_index in utility_vars:
        close_var = _add_soft_goal_closure_var(sas_task, var_index)
        close_condition = SASCondition(close_var.index, 1)
        open_condition = SASCondition(close_var.index, 0)
        closure_conditions.append(close_condition)

        max_utility = max(
            sas_task.utility_by_sas_value.get((var_index, value_index), 0.0)
            for value_index in range(len(sas_task.variables[var_index].values))
        )
        for value_index, value_name in enumerate(sas_task.variables[var_index].values):
            value_utility = sas_task.utility_by_sas_value.get(
                (var_index, value_index),
                0.0,
            )
            sas_task.actions.append(
                SASTranslatedAction(
                    index=len(sas_task.actions),
                    name=(
                        f"__close_soft_goal__v{var_index}"
                        f"__value{value_index}"
                    ),
                    conditions=(
                        SASCondition(var_index, value_index),
                        open_condition,
                    ),
                    effects=(close_condition,),
                    is_fictitious=True,
                    budget_cost=0.0,
                    utility_loss=max_utility - value_utility,
                )
            )

    _extend_goals_with_conditions(sas_task, closure_conditions)
    sas_task.initial_state = tuple(
        variable.initial_value for variable in sas_task.variables
    )
    sas_task.soft_goals_compiled = True
    return sas_task


# Handles the internal get utility vars step.
def _get_utility_vars(sas_task):
    return sorted(
        {
            var_index
            for (var_index, _value_index), utility in sas_task.utility_by_sas_value.items()
            if utility > 0.0
        }
    )


# Adds soft goal closure var.
def _add_soft_goal_closure_var(sas_task, utility_var_index):
    variable = SASVariable(
        index=len(sas_task.variables),
        name=f"closed_soft_goal_v{utility_var_index}",
        values=["open", "closed"],
        initial_value=0,
    )
    sas_task.variables.append(variable)
    sas_task.soft_goal_closure_vars.append(variable.index)
    return variable


# Handles the internal extend goals with conditions step.
def _extend_goals_with_conditions(sas_task, closure_conditions):
    closure_conditions = tuple(closure_conditions)
    if not closure_conditions:
        return

    if not sas_task.goals:
        sas_task.goals.append(
            SASTranslatedAction(
                index=0,
                name="__compiled_goal__",
                conditions=closure_conditions,
                is_goal=True,
            )
        )
        return

    for goal in sas_task.goals:
        goal.conditions = tuple(goal.conditions) + closure_conditions


class _SASTranslator:
    # Initializes this helper object.
    def __init__(self, task, grounder=None, utility_assignments=None):
        self.task = task
        self.grounder = grounder
        self.utility_assignments = utility_assignments
        if self.utility_assignments is None:
            problem = getattr(grounder, "problem", None)
            self.utility_assignments = list(getattr(problem, "utility", []))

        self.literal_vars = [
            var.index for var in task.variables if _is_boolean_var(var)
        ]
        self.literal_set = set(self.literal_vars)
        self.numeric_vars = [var for var in task.variables if var.isNumeric]
        self.reachable_literals = set()
        self.action_seen = set()
        self.mutex = set()
        self.mutex_changes = {}
        self.negated_precondition_literals = set()

    # Translates the grounded planning task into the reduced SAS representation.
    def translate(self):
        self._compute_mutex()

        sas_task = SASTask()
        self._create_numeric_variables(sas_task)
        self._create_sas_variables(sas_task)
        self._translate_actions(sas_task)
        self._translate_goals(sas_task)
        self._translate_utility(sas_task)
        self._compute_initial_states(sas_task)
        return sas_task

    # Computes mutex.
    def _compute_mutex(self):
        self.reachable_literals = {
            var.index
            for var in self.task.variables
            if _is_boolean_var(var) and _initial_bool_value(var) == BOOL_TRUE
        }

        self.mutex_changes = {literal: True for literal in self.reachable_literals}
        while self.mutex_changes:
            self.mutex_changes.clear()
            before = len(self.reachable_literals)

            for action in self.task.actions:
                self._check_action_for_mutex(action)

            if len(self.reachable_literals) == before and not self.mutex_changes:
                break

    # Checks action for mutex.
    def _check_action_for_mutex(self, action):
        preconditions = []
        for cond in action.conditions:
            if cond.varIndex not in self.literal_set:
                continue
            if cond.valueIndex == BOOL_FALSE:
                self.negated_precondition_literals.add(cond.varIndex)
                continue
            if cond.valueIndex != BOOL_TRUE:
                raise NotImplementedError(
                    f"Unsupported propositional condition value: {cond.valueIndex}"
                )
            if cond.varIndex not in self.reachable_literals:
                return
            preconditions.append(cond.varIndex)

        for i, first in enumerate(preconditions):
            for second in preconditions[i + 1:]:
                if self._are_mutex(first, second):
                    return

        self._update_mutex_with_action(action, preconditions)

    # Handles the internal update mutex with action step.
    def _update_mutex_with_action(self, action, preconditions):
        add = []
        delete = []
        new_literals = []

        for eff in action.effects:
            if eff.varIndex not in self.literal_set:
                continue
            if eff.valueIndex == BOOL_TRUE:
                add.append(eff.varIndex)
                if eff.varIndex not in self.reachable_literals:
                    new_literals.append(eff.varIndex)
            elif eff.valueIndex == BOOL_FALSE:
                delete.append(eff.varIndex)
            else:
                raise NotImplementedError(
                    f"Unsupported propositional effect value: {eff.valueIndex}"
                )

        for new_literal in new_literals:
            for deleted_literal in delete:
                if deleted_literal in preconditions or deleted_literal in add:
                    self._add_mutex(new_literal, deleted_literal)

            for precondition in preconditions:
                for other in self.literal_vars:
                    if (
                        other != new_literal
                        and other not in delete
                        and self._are_mutex(precondition, other)
                    ):
                        self._add_mutex(new_literal, other)

        if action.index not in self.action_seen:
            for i, first in enumerate(add):
                for second in add[i + 1:]:
                    if self._are_mutex(first, second):
                        self._delete_mutex(first, second)

        for added_literal in add:
            if added_literal in new_literals:
                continue
            for other in self.literal_vars:
                if other in delete or not self._are_mutex(added_literal, other):
                    continue
                has_mutex_precondition = any(
                    self._are_mutex(precondition, other)
                    for precondition in preconditions
                )
                if not has_mutex_precondition:
                    self._delete_mutex(added_literal, other)

        for literal in new_literals:
            if literal not in self.reachable_literals:
                self.reachable_literals.add(literal)
                self.mutex_changes[("reachable", literal)] = True

        self.action_seen.add(action.index)

    # Creates numeric variables.
    def _create_numeric_variables(self, sas_task):
        for var in self.numeric_vars:
            pos = len(sas_task.numeric_variables)
            sas_task.numeric_var_to_pos[var.index] = pos
            sas_task.numeric_variables.append(var)

    # Creates sas variables.
    def _create_sas_variables(self, sas_task):
        components = _MutexGraph(self.literal_vars, self.mutex).split()

        for component in components:
            use_boolean_vars = (
                len(component) == 1
                or any(literal in self.negated_precondition_literals for literal in component)
            )
            if use_boolean_vars:
                for literal in component:
                    self._create_boolean_sas_var(sas_task, literal)
            else:
                self._create_grouped_sas_var(sas_task, component)

    # Creates boolean sas var.
    def _create_boolean_sas_var(self, sas_task, literal):
        index = len(sas_task.variables)
        variable = SASVariable(
            index=index,
            name=_literal_name(self.task, self.grounder, literal),
            values=[SAS_FALSE, SAS_TRUE],
            initial_value=(
                1
                if _initial_bool_value(self.task.variables[literal]) == BOOL_TRUE
                else 0
            ),
        )
        sas_task.variables.append(variable)
        sas_task.literal_to_sas[literal] = (index, 1)
        sas_task.sas_to_literal[(index, 1)] = literal

    # Creates grouped sas var.
    def _create_grouped_sas_var(self, sas_task, component):
        index = len(sas_task.variables)
        values = [
            _literal_name(self.task, self.grounder, literal)
            for literal in component
        ]
        true_initial = [
            pos
            for pos, literal in enumerate(component)
            if _initial_bool_value(self.task.variables[literal]) == BOOL_TRUE
        ]

        if len(true_initial) > 1:
            raise ValueError(
                "Initial state has multiple true literals in one SAS mutex group."
            )

        if true_initial:
            initial_value = true_initial[0]
        else:
            initial_value = len(values)
            values.append(SAS_NONE)

        variable = SASVariable(
            index=index,
            name=f"sas-group-{index}",
            values=values,
            initial_value=initial_value,
        )
        sas_task.variables.append(variable)

        for value, literal in enumerate(component):
            sas_task.literal_to_sas[literal] = (index, value)
            sas_task.sas_to_literal[(index, value)] = literal

    # Translates actions.
    def _translate_actions(self, sas_task):
        for action in self.task.actions:
            if getattr(action, "isGoal", False):
                continue
            sas_task.actions.append(self._translate_action(sas_task, action, False))

    # Translates goals.
    def _translate_goals(self, sas_task):
        for goal in self.task.goals:
            sas_task.goals.append(self._translate_action(sas_task, goal, True))

    # Translates action.
    def _translate_action(self, sas_task, action, is_goal):
        conditions = tuple(
            self._translate_condition(sas_task, cond)
            for cond in action.conditions
        )
        effects = self._translate_effects(sas_task, action.effects)
        return SASTranslatedAction(
            index=len(sas_task.goals) if is_goal else len(sas_task.actions),
            name=action.name,
            parameters=tuple(action.parameters),
            conditions=conditions,
            numeric_conditions=tuple(action.numericConditions),
            effects=tuple(effects),
            numeric_effects=tuple(action.numericEffects),
            original_action=action,
            is_goal=is_goal,
        )

    # Translates condition.
    def _translate_condition(self, sas_task, cond):
        if cond.varIndex not in sas_task.literal_to_sas:
            raise NotImplementedError(
                "Only boolean propositional SAS conditions are supported."
            )

        sas_var, sas_value = sas_task.literal_to_sas[cond.varIndex]
        if cond.valueIndex == BOOL_TRUE:
            return SASCondition(sas_var, sas_value)
        if cond.valueIndex == BOOL_FALSE:
            values = sas_task.variables[sas_var].values
            if len(values) != 2:
                raise NotImplementedError(
                    "Negative preconditions on grouped SAS variables are not supported."
                )
            return SASCondition(sas_var, 1 - sas_value)
        raise NotImplementedError(
            f"Unsupported propositional condition value: {cond.valueIndex}"
        )

    # Translates effects.
    def _translate_effects(self, sas_task, effects):
        translated = []
        true_effect_by_sas_var = {}

        for eff in effects:
            if eff.varIndex not in sas_task.literal_to_sas:
                raise NotImplementedError(
                    "Only boolean propositional SAS effects are supported."
                )
            if eff.valueIndex == BOOL_TRUE:
                sas_var, sas_value = sas_task.literal_to_sas[eff.varIndex]
                true_effect_by_sas_var[sas_var] = sas_value
                translated.append(SASCondition(sas_var, sas_value))

        for eff in effects:
            if eff.valueIndex != BOOL_FALSE:
                continue
            sas_var, sas_value = sas_task.literal_to_sas[eff.varIndex]
            if sas_var in true_effect_by_sas_var:
                continue
            values = sas_task.variables[sas_var].values
            if len(values) == 2 and values == [SAS_FALSE, SAS_TRUE]:
                translated.append(SASCondition(sas_var, 0))
            elif SAS_NONE in values:
                translated.append(SASCondition(sas_var, values.index(SAS_NONE)))
            else:
                raise NotImplementedError(
                    "Delete-only effect on grouped SAS variable without none value."
                )

        return _deduplicate_conditions(translated)

    # Translates utility.
    def _translate_utility(self, sas_task):
        for assignment in self.utility_assignments:
            literal = _find_literal_from_utility_assignment(
                self.task,
                self.grounder,
                assignment,
            )
            if literal is None:
                raise ValueError(f"Utility literal not found: {assignment}")
            sas_task.utility_by_literal[literal] = float(assignment.value)

            sas_key = sas_task.literal_to_sas.get(literal)
            if sas_key is None:
                raise ValueError(f"Utility literal was not translated: {assignment}")
            sas_task.utility_by_sas_value[sas_key] = float(assignment.value)

    # Computes initial states.
    def _compute_initial_states(self, sas_task):
        sas_task.initial_state = tuple(
            variable.initial_value for variable in sas_task.variables
        )
        numeric_values = []
        for var in sas_task.numeric_variables:
            if var.initialValues:
                numeric_values.append(float(var.initialValues[0].numericValue))
            else:
                numeric_values.append(0.0)
        sas_task.numeric_initial_state = tuple(numeric_values)

    # Handles the internal are mutex step.
    def _are_mutex(self, first, second):
        if first == second:
            return False
        return _mutex_key(first, second) in self.mutex

    # Adds mutex.
    def _add_mutex(self, first, second):
        if first == second:
            return
        key = _mutex_key(first, second)
        if key not in self.mutex:
            self.mutex.add(key)
            self.mutex_changes[key] = True

    # Removes mutex.
    def _delete_mutex(self, first, second):
        key = _mutex_key(first, second)
        if key in self.mutex:
            self.mutex.remove(key)
            self.mutex_changes[key] = False


class _MutexGraph:
    # Initializes this helper object.
    def __init__(self, vertices, mutex):
        self.vertices = list(vertices)
        self.vertex_set = set(vertices)
        self.adjacent = {vertex: set() for vertex in vertices}
        for first, second in mutex:
            if first in self.vertex_set and second in self.vertex_set:
                self.adjacent[first].add(second)
                self.adjacent[second].add(first)

    # Splits the graph into mutex-compatible components.
    def split(self):
        remaining = set(self.vertices)
        components = []
        while remaining:
            origin = min(remaining)
            component = self._maximal_mutex_component(origin, remaining)
            components.append(component)
            remaining.difference_update(component)
        return components

    # Handles the internal maximal mutex component step.
    def _maximal_mutex_component(self, origin, candidates):
        component = [origin]
        for candidate in sorted(candidates - {origin}):
            if all(candidate in self.adjacent[member] for member in component):
                component.append(candidate)
        return component


# Checks whether boolean var.
def _is_boolean_var(var):
    return not var.isNumeric


# Handles the internal default missing value step.
def _default_missing_value(var):
    if var.values == [SAS_FALSE, SAS_TRUE]:
        return 0
    if var.values == ["open", "closed"]:
        return 0
    if SAS_NONE in var.values:
        return var.values.index(SAS_NONE)
    return None


# Handles the internal initial bool value step.
def _initial_bool_value(var):
    if var.initialValues:
        return var.initialValues[0].value
    return BOOL_FALSE


# Handles the internal mutex key step.
def _mutex_key(first, second):
    if first > second:
        first, second = second, first
    return first, second


# Handles the internal literal name step.
def _literal_name(task, grounder, literal):
    if grounder is None:
        return f"var_{literal}"
    var = task.variables[literal]
    params = [
        getattr(grounder.objects[param], "name", str(param))
        for param in var.params
    ]
    if params:
        return f"{var.fncIndex}({', '.join(params)})"
    return str(var.fncIndex)


# Handles the internal find literal from utility assignment step.
def _find_literal_from_utility_assignment(task, grounder, assignment):
    wanted = (
        str(assignment.predicate),
        tuple(str(arg) for arg in assignment.arguments),
    )
    for var in task.variables:
        if var.isNumeric or str(var.fncIndex) != wanted[0]:
            continue
        args = tuple(_param_name(grounder, param) for param in var.params)
        if args == wanted[1]:
            return var.index
    return None


# Handles the internal param name step.
def _param_name(grounder, param):
    if grounder is None:
        return str(param)
    return getattr(grounder.objects[param], "name", str(param))


# Handles the internal deduplicate conditions step.
def _deduplicate_conditions(conditions):
    seen = set()
    result = []
    for condition in conditions:
        key = (condition.var, condition.value)
        if key in seen:
            continue
        seen.add(key)
        result.append(condition)
    return tuple(result)


# Checks sas conditions.
def _check_sas_conditions(sas_state, conditions):
    return all(sas_state[condition.var] == condition.value for condition in conditions)


# Checks numeric conditions.
def _check_numeric_conditions(numeric_state, conditions, sas_task):
    return all(
        _evaluate_numeric_condition(numeric_state, condition, sas_task)
        for condition in conditions
    )


# Evaluates numeric condition.
def _evaluate_numeric_condition(numeric_state, condition, sas_task):
    if len(condition.terms) != 2:
        raise NotImplementedError("Only binary numeric conditions are supported.")

    left = _evaluate_numeric_expression(numeric_state, condition.terms[0], sas_task)
    right = _evaluate_numeric_expression(numeric_state, condition.terms[1], sas_task)
    comparator = condition.comparator

    if comparator == Comparator.CMP_EQ:
        return left == right
    if comparator == Comparator.CMP_NEQ:
        return left != right
    if comparator == Comparator.CMP_LESS:
        return left < right
    if comparator == Comparator.CMP_LESS_EQ:
        return left <= right
    if comparator == Comparator.CMP_GREATER:
        return left > right
    if comparator == Comparator.CMP_GREATER_EQ:
        return left >= right

    raise NotImplementedError(f"Unsupported numeric comparator: {comparator}")


# Evaluates numeric expression.
def _evaluate_numeric_expression(numeric_state, expression, sas_task):
    expression_type = expression.type

    if expression_type == GroundedNumericExpressionType.GE_NUMBER:
        return float(expression.value)

    if expression_type == GroundedNumericExpressionType.GE_VAR:
        pos = sas_task.numeric_var_to_pos[expression.index]
        return numeric_state[pos]

    if expression_type == GroundedNumericExpressionType.GE_SUM:
        return sum(
            _evaluate_numeric_expression(numeric_state, sub, sas_task)
            for sub in expression.terms
        )

    if expression_type == GroundedNumericExpressionType.GE_SUB:
        values = [
            _evaluate_numeric_expression(numeric_state, sub, sas_task)
            for sub in expression.terms
        ]
        if len(values) == 1:
            return -values[0]
        result = values[0]
        for value in values[1:]:
            result -= value
        return result

    if expression_type == GroundedNumericExpressionType.GE_MUL:
        result = 1.0
        for sub in expression.terms:
            result *= _evaluate_numeric_expression(numeric_state, sub, sas_task)
        return result

    if expression_type == GroundedNumericExpressionType.GE_DIV:
        values = [
            _evaluate_numeric_expression(numeric_state, sub, sas_task)
            for sub in expression.terms
        ]
        if len(values) != 2:
            raise NotImplementedError("GE_DIV is only supported with two operands.")
        return values[0] / values[1]

    raise NotImplementedError(f"Unsupported numeric expression: {expression_type}")


# Applies numeric effect.
def _apply_numeric_effect(next_numeric_state, old_numeric_state, effect, sas_task):
    pos = sas_task.numeric_var_to_pos[effect.varIndex]
    current_value = next_numeric_state[pos]
    rhs = _evaluate_numeric_expression(old_numeric_state, effect.exp, sas_task)

    if effect.assignment == Assignment.AS_ASSIGN:
        new_value = rhs
    elif effect.assignment == Assignment.AS_INCREASE:
        new_value = current_value + rhs
    elif effect.assignment == Assignment.AS_DECREASE:
        new_value = current_value - rhs
    elif effect.assignment == Assignment.AS_SCALE_UP:
        new_value = current_value * rhs
    elif effect.assignment == Assignment.AS_SCALE_DOWN:
        new_value = current_value / rhs
    else:
        raise NotImplementedError(
            f"Unsupported numeric assignment: {effect.assignment}"
        )

    next_numeric_state[pos] = new_value
