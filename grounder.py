from collections import defaultdict
from pddl.logic.base import Not, And
from pddl.logic.predicates import Predicate
from pddl.logic.functions import NumericFunction, NumericValue
from pddl.logic.terms import Variable, Constant
from grounderTypes import (GroundedTask, ProgrammedValue, GroundedVar,
    GroundedValue, TermType, GrounderOperator, Term, Literal, OpFluent,
    SyntheticOperator, GroundedAction, Comparator, GroundedNumericCondition,
    GroundedNumericExpression, GroundedNumericExpressionType, Assignment,
    GroundedNumericEffect, OpEquality, GroundedCondition, GroundedMetric,
    MetricExpressionType, NumericVariableRef, BOOL_TRUE, BOOL_FALSE)

class Grounder:
    # Initializes this object.
    def __init__(self, task):
        self.domain, self.problem = task
        self.typesMatrix = []
        self.type_list = []
        self.type_to_index = {}

        self.objects = []
        self.ops = []
        self.numOps = 0
        self.opRequireFunction = defaultdict(list)

        self.gTask = GroundedTask()
        self.variableIndex = {}

        self.newValues = []
        self.auxValues = []
        self.valuesByFunction = defaultdict(list)

        self.numValues = 0
        self.startNewValues = 0
        self.object_list = []
        self.object_to_index = {}
        self.groundedActions = {}
    
    # Initializes object/type lookup structures used during grounding.
    def initObjects(self):
        problem_objects = list(self.problem.objects)
        domain_constants = list(getattr(self.domain, "constants", []))
    
        self.object_list = []
        self.object_to_index = {}
    
        for obj in problem_objects + domain_constants:
            name = getattr(obj, "name", str(obj))
            if name not in self.object_to_index:
                idx = len(self.object_list)
                self.object_list.append(obj)
                self.object_to_index[name] = idx
                
    # Runs the full grounding pipeline and returns a grounded task.
    def ground(self):
        self.currentLevel = 0
        self.initTypesMatrix()
        self.initObjects()
        self.initOperators()
        self.initInitialState()
        for op in self.ops:
            if len(op.preconditions) == 0:
                self.groundRemainingParameters(op)
    
        for pv in self.auxValues:
            self.newValues.append(pv)
            fnc_index = self.gTask.variables[pv.varIndex].fncIndex
            self.valuesByFunction[fnc_index].append(pv)
    
        self.auxValues.clear()
    
        while len(self.newValues) > 0:
            for pv in self.newValues:
                self.match(pv)
    
            self.startNewValues += len(self.newValues)
            self.swapLevels()
            self.currentLevel += 1
        
        metric = getattr(self.problem, "metric", None)

        if metric is None:
            self.gTask.metricType = "X"
        else:
            self.gTask.metricType = self._get_metric_direction(metric)
            self.gTask.metric = self.groundMetric(self._get_metric_expression(metric))
        
        self.removeStaticVariables()

        return self.gTask

    # Removes static variables and simplifies actions that depend on them.
    def removeStaticVariables(self):
        num_vars = len(self.gTask.variables)
        num_actions = len(self.gTask.actions)
        invalid_index = None

        static_var = [True] * num_vars
        new_index = []
        values = []

        for i in range(num_actions):
            self.checkStaticVariables(self.gTask.actions[i], static_var)

        next_index = 0
        for i in range(num_vars):
            if static_var[i]:
                init_values = self.getInitialValues(i)
                v = self._build_static_variable_value(i, init_values)

                # En tu versión actual no trasladamos TIL. Si alguna vez aparecen
                # varios valores iniciales o alguno con tiempo > 0, dejamos de
                # considerarla estática por seguridad.
                if len(init_values) > 1:
                    static_var[i] = False
                elif len(init_values) == 1 and getattr(init_values[0], "time", 0.0) > 0:
                    static_var[i] = False

                values.append(v)

                if static_var[i]:
                    new_index.append(invalid_index)   # se eliminaría
                else:
                    new_index.append(next_index)
                    next_index += 1
            else:
                values.append(None)
                new_index.append(next_index)
                next_index += 1

        self.removeStaticVariables_impl(static_var, new_index, values)

        for i, var in enumerate(self.gTask.variables):
            var.index = i
    
    # Builds static variable value.
    def _build_static_variable_value(self, var_index, init_values):
        var = self.gTask.variables[var_index]

        if len(init_values) == 0:
            if not var.isNumeric:
                return {
                    "valueIsNumeric": False,
                    "value": BOOL_FALSE,
                    "numericValue": 0.0,
                }
            else:
                return {
                    "valueIsNumeric": False,
                    "value": None,
                    "numericValue": 0.0,
                }

        f = init_values[0]
        if var.isNumeric:
            return {
                "valueIsNumeric": True,
                "value": None,
                "numericValue": f.numericValue,
            }

        return {
            "valueIsNumeric": False,
            "value": f.value,
            "numericValue": 0.0,
        }

    
    # Checks whether an action can use a static variable for simplification.
    def checkStaticVariables(self, action, static_var):
        for eff in action.effects:
            static_var[eff.varIndex] = False

        for eff in action.numericEffects:
            static_var[eff.varIndex] = False
            
    # Returns the initially true values for a grounded variable.
    def getInitialValues(self, var_index):
        return list(self.gTask.variables[var_index].initialValues)
    
    # Rewrites variables, actions, and goals after removing a static variable.
    def removeStaticVariables_impl(self, static_var, new_index, values):
        # 1) Acciones
        new_actions = []
        for i, action in enumerate(self.gTask.actions):
            action.index = i
            remove = self._remove_static_from_action(action, static_var, new_index, values)
            if not remove:
                new_actions.append(action)
        self.gTask.actions = new_actions
    
        # 2) Goals
        new_goals = []
        for i, goal in enumerate(self.gTask.goals):
            goal.index = i
            remove = self._remove_static_from_action(goal, static_var, new_index, values)
            if not remove:
                new_goals.append(goal)
        self.gTask.goals = new_goals
    
        # 3) Compactar variables y reachedValues
        old_variables = list(self.gTask.variables)
        old_reached_values = list(self.gTask.reachedValues)
    
        kept_variables = []
        kept_reached_values = []
        self.variableIndex = {}
    
        for old_i, is_static in enumerate(static_var):
            if not is_static:
                v = old_variables[old_i]
                rv = old_reached_values[old_i]
    
                v.index = len(kept_variables)
                kept_variables.append(v)
                kept_reached_values.append(rv)
    
                name = self.getVariableName(v.fncIndex, v.params)
                self.variableIndex[name] = v.index
    
        self.gTask.variables = kept_variables
        self.gTask.reachedValues = kept_reached_values
    
        # 5) Métrica
        if self.gTask.metricType != "X" and self.gTask.metric is not None:
            if self._remove_static_from_metric(self.gTask.metric, static_var, new_index, values):
                raise ValueError("La métrica hace referencia a una variable estática numérica sin valor definido.")
    
    # Removes static from action.
    def _remove_static_from_action(self, action, static_var, new_index, values):
        remove = False
    
        if not remove:
            remove = self._remove_static_from_conditions(
                action.conditions, static_var, new_index, values
            )
    
        if not remove:
            remove = self._remove_static_from_conditions(
                action.effects, static_var, new_index, values
            )
    
        if not remove:
            remove = self._remove_static_from_numeric_conditions(
                action.numericConditions, static_var, new_index, values
            )
    
        if not remove:
            remove = self._remove_static_from_numeric_effects(
                action.numericEffects, static_var, new_index, values
            )
    
        return remove
    
    # Removes static from conditions.
    def _remove_static_from_conditions(self, conds, static_var, new_index, values):
        i = 0
        while i < len(conds):
            c = conds[i]
    
            if static_var[c.varIndex]:
                val = values[c.varIndex]
    
                # variable estática sin valor definido
                if (not val["valueIsNumeric"]) and val["value"] is None:
                    return True
    
                if val["value"] == c.valueIndex:
                    conds.pop(i)
                else:
                    return True
            else:
                c.varIndex = new_index[c.varIndex]
                i += 1
    
        return False
    
    # Removes static from numeric conditions.
    def _remove_static_from_numeric_conditions(self, conds, static_var, new_index, values):
        i = 0
        while i < len(conds):
            c = conds[i]
    
            all_numbers = True
            for term in c.terms:
                if self._remove_static_from_numeric_expression(term, static_var, new_index, values):
                    return True
                if term.type != GroundedNumericExpressionType.GE_NUMBER:
                    all_numbers = False
    
            if all_numbers:
                if self._numeric_comparison_holds(c):
                    i += 1
                else:
                    return True
            else:
                i += 1
    
        return False
    
    # Removes static from numeric effects.
    def _remove_static_from_numeric_effects(self, effs, static_var, new_index, values):
        for e in effs:
            if static_var[e.varIndex]:
                # En teoría no debería ocurrir, porque toda variable modificada ya fue marcada no estática.
                return True
    
            e.varIndex = new_index[e.varIndex]
    
            if self._remove_static_from_numeric_expression(e.exp, static_var, new_index, values):
                return True
    
        return False
    
    # Removes static from numeric expression.
    def _remove_static_from_numeric_expression(self, expr, static_var, new_index, values):
        t = expr.type
    
        if t == GroundedNumericExpressionType.GE_VAR:
            if static_var[expr.index]:
                val = values[expr.index]
    
                if (not val["valueIsNumeric"]) and val["value"] is None:
                    return True
    
                expr.type = GroundedNumericExpressionType.GE_NUMBER
                expr.value = val["numericValue"]
                expr.index = 0
                expr.terms = []
                expr.variable = None
            else:
                expr.index = new_index[expr.index]
    
        elif t in {
            GroundedNumericExpressionType.GE_SUM,
            GroundedNumericExpressionType.GE_SUB,
            GroundedNumericExpressionType.GE_DIV,
            GroundedNumericExpressionType.GE_MUL,
            GroundedNumericExpressionType.GE_SHARP_T,
        }:
            can_compute = True
    
            for sub in expr.terms:
                if self._remove_static_from_numeric_expression(sub, static_var, new_index, values):
                    return True
                if sub.type != GroundedNumericExpressionType.GE_NUMBER:
                    can_compute = False
    
            if can_compute:
                expr.value = self._compute_numeric_expression_value(expr)
                expr.type = GroundedNumericExpressionType.GE_NUMBER
                expr.index = 0
                expr.terms = []
                expr.variable = None
    
        return False
    
    # Handles numeric comparison holds.
    def _numeric_comparison_holds(self, cond):
        if len(cond.terms) != 2:
            raise NotImplementedError("Solo se soportan comparaciones numéricas binarias.")
    
        left = cond.terms[0].value
        right = cond.terms[1].value
        cmp_ = cond.comparator
    
        if cmp_ == Comparator.CMP_EQ:
            return left == right
        if cmp_ == Comparator.CMP_NEQ:
            return left != right
        if cmp_ == Comparator.CMP_LESS:
            return left < right
        if cmp_ == Comparator.CMP_LESS_EQ:
            return left <= right
        if cmp_ == Comparator.CMP_GREATER:
            return left > right
        if cmp_ == Comparator.CMP_GREATER_EQ:
            return left >= right
    
        raise NotImplementedError(f"Comparador no soportado: {cmp_}")
        
    # Computes numeric expression value.
    def _compute_numeric_expression_value(self, expr):
        t = expr.type
    
        if t == GroundedNumericExpressionType.GE_NUMBER:
            return expr.value
    
        vals = [self._compute_numeric_expression_value(sub) for sub in expr.terms]
    
        if t == GroundedNumericExpressionType.GE_SUM:
            return sum(vals)
    
        if t == GroundedNumericExpressionType.GE_SUB:
            if len(vals) == 1:
                return -vals[0]
            result = vals[0]
            for v in vals[1:]:
                result -= v
            return result
    
        if t == GroundedNumericExpressionType.GE_MUL:
            result = 1.0
            for v in vals:
                result *= v
            return result
    
        if t == GroundedNumericExpressionType.GE_DIV:
            if len(vals) != 2:
                raise NotImplementedError("GE_DIV solo se soporta con dos operandos.")
            return vals[0] / vals[1]
    
        raise NotImplementedError(f"No se puede evaluar la expresión numérica de tipo {t}")
    
    # Removes static from metric.
    def _remove_static_from_metric(self, metric, static_var, new_index, values):
        t = metric.type
    
        if t == MetricExpressionType.MT_FLUENT:
            if static_var[metric.index]:
                val = values[metric.index]
    
                if (not val["valueIsNumeric"]) and val["value"] is None:
                    return True
    
                metric.type = MetricExpressionType.MT_NUMBER
                metric.value = val["numericValue"]
                metric.index = 0
                metric.terms = []
            else:
                metric.index = new_index[metric.index]
    
        elif t in {
            MetricExpressionType.MT_PLUS,
            MetricExpressionType.MT_MINUS,
            MetricExpressionType.MT_PROD,
            MetricExpressionType.MT_DIV,
        }:
            can_compute = True
    
            for sub in metric.terms:
                if self._remove_static_from_metric(sub, static_var, new_index, values):
                    return True
                if sub.type != MetricExpressionType.MT_NUMBER:
                    can_compute = False
    
            if can_compute:
                metric.value = self._compute_metric_value(metric)
                metric.type = MetricExpressionType.MT_NUMBER
                metric.index = 0
                metric.terms = []
    
        return False

    # Computes metric value.
    def _compute_metric_value(self, metric):
        t = metric.type
    
        if t == MetricExpressionType.MT_NUMBER:
            return metric.value
    
        vals = [self._compute_metric_value(sub) for sub in metric.terms]
    
        if t == MetricExpressionType.MT_PLUS:
            return sum(vals)
    
        if t == MetricExpressionType.MT_MINUS:
            if len(vals) == 1:
                return -vals[0]
            result = vals[0]
            for v in vals[1:]:
                result -= v
            return result
    
        if t == MetricExpressionType.MT_PROD:
            result = 1.0
            for v in vals:
                result *= v
            return result
    
        if t == MetricExpressionType.MT_DIV:
            if len(vals) != 2:
                raise NotImplementedError("MT_DIV solo se soporta con dos operandos.")
            return vals[0] / vals[1]
    
        raise NotImplementedError(f"No se puede evaluar la métrica de tipo {t}")
        
    # Returns metric direction.
    def _get_metric_direction(self, metric):
        """
        Devuelve:
          '>' si es maximize
          '<' si es minimize
          'X' si no hay métrica
        """
        # Casos típicos: atributo explícito
        for attr in ("direction", "optimization", "metric_type", "kind"):
            value = getattr(metric, attr, None)
            if value is not None:
                text = str(value).lower()
                if "max" in text:
                    return ">"
                if "min" in text:
                    return "<"

        # Respaldo: parsear el repr/str
        text = str(metric).lower()
        if "maximize" in text:
            return ">"
        if "minimize" in text:
            return "<"

        raise ValueError(f"No puedo determinar la dirección de la métrica: {metric!r}")

    # Returns metric expression.
    def _get_metric_expression(self, metric):
        """
        Extrae la expresión interna de la métrica.
        """
        for attr in ("expression", "expr", "metric", "term", "value"):
            expr = getattr(metric, attr, None)
            if expr is not None:
                return expr

        # Si no encontramos nada estructurado, no seguimos a ciegas
        raise ValueError(f"No puedo extraer la expresión de la métrica: {metric!r}")
        
    # Grounds an optimization metric expression.
    def groundMetric(self, expr):
        # Número
        if isinstance(expr, NumericValue):
            return GroundedMetric(
                type=MetricExpressionType.MT_NUMBER,
                value=float(expr.value),
            )

        # Fluente numérico
        if isinstance(expr, NumericFunction):
            params = [self._term_to_index_or_name(t) for t in expr.terms]
            var_name = self.getVariableName(expr.name, params)
            return GroundedMetric(
                type=MetricExpressionType.MT_FLUENT,
                index=self.variableIndex[var_name],
            )

        # Operadores aritméticos
        cls = expr.__class__.__name__
        if hasattr(expr, "operands"):
            grounded_terms = [self.groundMetric(t) for t in expr.operands]

            if cls == "Sum":
                t = MetricExpressionType.MT_PLUS
            elif cls == "Subtraction":
                t = MetricExpressionType.MT_MINUS
            elif cls == "Multiplication":
                t = MetricExpressionType.MT_PROD
            elif cls == "Division":
                t = MetricExpressionType.MT_DIV
            else:
                raise NotImplementedError(f"Expresión de métrica no soportada: {expr!r}")

            return GroundedMetric(type=t, terms=grounded_terms)

        raise NotImplementedError(f"Expresión de métrica no soportada: {expr!r}")

    # Initializes the type compatibility matrix.
    def initTypesMatrix(self):
        # domain.types es un dict: subtype -> parent
        type_dict = self.domain.types

        # Incluye tanto subtipos definidos como ancestros que aparezcan solo como valor.
        all_types = set(type_dict.keys())
        all_types.update(parent for parent in type_dict.values() if parent is not None)

        # Conviene fijar un orden estable para indexar.
        self.type_list = sorted(all_types)
        self.type_to_index = {
            type_name: i for i, type_name in enumerate(self.type_list)
        }

        num_types = len(self.type_list)
        self.typesMatrix = [[False] * num_types for _ in range(num_types)]

        for i in range(num_types):
            self.addTypeToMatrix(i, i)

    # Adds subtype relationships to the type compatibility matrix.
    def addTypeToMatrix(self, typeIndex, subtypeIndex):
        if self.typesMatrix[typeIndex][subtypeIndex]:
            return

        self.typesMatrix[typeIndex][subtypeIndex] = True

        subtype_name = self.type_list[subtypeIndex]
        parent_name = self.domain.types.get(subtype_name)

        if parent_name is not None:
            parent_index = self.type_to_index[parent_name]
            self.addTypeToMatrix(typeIndex, parent_index)
            
    # Converts parsed PDDL operators into internal operator templates.
    def initOperators(self):
        self.objects = list(self.object_list)    
        actions = list(self.domain.actions)
    
        goal_op = SyntheticOperator(
            name="__goal__",
            parameters=[],
            precondition=self.problem.goal,
            effect=None,
            instantaneous=True,
            isTIL=False,
            isGoal=True,
        )
    
        all_ops = actions + [goal_op]
    
        self.numOps = len(all_ops)
        self.ops = []
    
        for i, action in enumerate(all_ops):
            g = GrounderOperator()
            g.index = i
    
            preconditions, numericPreconditions, equality = self._extract_preconditions(action.precondition, action)
            effects, numericEffects = self._extract_effects(action.effect, action)
            action.equality = list(equality)
            g.initialize(action, preconditions, numericPreconditions, effects, numericEffects, equality)
            
            for j, param in enumerate(action.parameters):
                required_types = self._get_parameter_types(param)
    
                for k in range(len(self.objects)):
                    if self.objectIsCompatible(k, required_types):
                        g.compatibleObjectsWithParam[j].append(k)
    
            self.ops.append(g)
    
        self.opRequireFunction.clear()
    
        for g in self.ops:
            required_symbols = self._extract_required_symbols(g.preconditions)
            for symbol in required_symbols:
                self.addOpToRequireFunction(g, symbol)
                
    # Checks whether an object satisfies the required parameter types.
    def objectIsCompatible(self, objIndex, required_types):
        obj = self.objects[objIndex]
        obj_type = getattr(obj, "type_tag", None)

        if obj_type is None:
            return len(required_types) == 0

        if not required_types:
            return True

        obj_type_index = self.type_to_index[obj_type]

        for required_type in required_types:
            required_index = self.type_to_index[required_type]
            if self.typesMatrix[obj_type_index][required_index]:
                return True

        return False
    
    # Indexes operators by the symbols required in their preconditions.
    def addOpToRequireFunction(self, op, symbol):
        bucket = self.opRequireFunction[symbol]
        if op not in bucket:
            bucket.append(op)
            
    # Returns parameter types.
    def _get_parameter_types(self, param):
        type_tags = getattr(param, "type_tags", None)
        if not type_tags:
            return []
        return list(type_tags)
    
    # Extracts preconditions.
    def _extract_preconditions(self, cond, action):
        bool_pre = []
        num_pre = []
        eq_pre = []
    
        if cond is None:
            return bool_pre, num_pre, eq_pre
    
        if isinstance(cond, And):
            for sub in cond.operands:
                sub_bool, sub_num, sub_eq = self._extract_preconditions(sub, action)
                bool_pre.extend(sub_bool)
                num_pre.extend(sub_num)
                eq_pre.extend(sub_eq)
            return bool_pre, num_pre, eq_pre
    
        if self._is_term_equality_condition(cond):
            eq_pre.append(self._condition_to_op_equality(cond, action))
        elif self._is_numeric_condition(cond):
            num_pre.append(self._condition_to_grounded_numeric_condition(cond, action))
        else:
            bool_pre.append(self._condition_to_opfluent(cond, action))
    
        return bool_pre, num_pre, eq_pre
    
    # Returns binary operands.
    def _get_binary_operands(self, expr):
        if hasattr(expr, "left") and hasattr(expr, "right"):
            return expr.left, expr.right
    
        operands = getattr(expr, "operands", None)
        if operands is not None and len(operands) == 2:
            return operands[0], operands[1]
    
        raise NotImplementedError(
            f"No puedo extraer dos operandos de la expresión: {expr!r}"
        )
    
    # Converts to grounded numeric condition.
    def _condition_to_grounded_numeric_condition(self, cond, action):
        left, right = self._get_binary_operands(cond)
    
        return GroundedNumericCondition(
            comparator=self._get_comparator(cond),
            terms=[
                self._numeric_expression_to_grounded(left, action),
                self._numeric_expression_to_grounded(right, action),
            ],
        )
    
    # Extracts effects.
    def _extract_effects(self, eff, action):
        bool_eff = []
        num_eff = []
    
        if eff is None:
            return bool_eff, num_eff
    
        if isinstance(eff, And):
            for sub in eff.operands:
                sub_bool, sub_num = self._extract_effects(sub, action)
                bool_eff.extend(sub_bool)
                num_eff.extend(sub_num)
            return bool_eff, num_eff
    
        if eff.__class__.__name__ in {"Increase", "Decrease", "Assign", "ScaleUp", "ScaleDown"}:
            num_eff.append(self._effect_to_grounded_numeric_effect(eff, action))
        else:
            bool_eff.append(self._condition_to_opfluent(eff, action))
    
        return bool_eff, num_eff
    
    # Converts to grounded numeric effect.
    def _effect_to_grounded_numeric_effect(self, eff, action):
        cls_name = eff.__class__.__name__
    
        if cls_name == "Increase":
            assignment = Assignment.AS_INCREASE
        elif cls_name == "Decrease":
            assignment = Assignment.AS_DECREASE
        elif cls_name == "Assign":
            assignment = Assignment.AS_ASSIGN
        elif cls_name == "ScaleUp":
            assignment = Assignment.AS_SCALE_UP
        elif cls_name == "ScaleDown":
            assignment = Assignment.AS_SCALE_DOWN
        else:
            raise NotImplementedError(f"Efecto numérico no soportado: {eff!r}")
    
        if hasattr(eff, "left") and hasattr(eff, "right"):
            lhs = eff.left
            rhs = eff.right
        else:
            operands = getattr(eff, "operands", None)
            if not operands or len(operands) != 2:
                raise NotImplementedError(
                    f"No puedo extraer los operandos del efecto numérico: {eff!r}"
                )
            lhs, rhs = operands
    
        if not isinstance(lhs, NumericFunction):
            raise NotImplementedError(
                f"El lado izquierdo del efecto numérico debe ser NumericFunction: {eff!r}"
            )
    
        var_ref = self._numeric_function_to_numeric_ref(lhs, action)
        exp = self._numeric_expression_to_grounded(rhs, action)
    
        return GroundedNumericEffect(
            assignment=assignment,
            variable=var_ref,
            exp=exp,
        )
    
    # Checks whether numeric condition.
    def _is_numeric_condition(self, cond):
        return cond.__class__.__name__ in {
            "EqualTo",
            "NotEqualTo",
            "LesserThan",
            "LesserEqualThan",
            "GreaterThan",
            "GreaterEqualThan",
        }
    
    # Converts to op equality.
    def _condition_to_op_equality(self, cond, action):
        left, right = self._get_binary_operands(cond)
        param_index = self._build_action_param_index(action)
    
        value1 = self._term_to_grounder_term(left, param_index)
        value2 = self._term_to_grounder_term(right, param_index)
    
        return OpEquality(
            value1=value1,
            value2=value2,
            equal=(cond.__class__.__name__ == "EqualTo"),
        )
    
    # Returns comparator.
    def _get_comparator(self, cond):
        name = cond.__class__.__name__
    
        if name == "EqualTo":
            return Comparator.CMP_EQ
        if name == "NotEqualTo":
            return Comparator.CMP_NEQ
        if name == "LesserThan":
            return Comparator.CMP_LESS
        if name == "LesserEqualThan":
            return Comparator.CMP_LESS_EQ
        if name == "GreaterThan":
            return Comparator.CMP_GREATER
        if name == "GreaterEqualThan":
            return Comparator.CMP_GREATER_EQ
    
        raise NotImplementedError(f"Comparador no soportado: {name}")
        
    # Extracts required symbols.
    def _extract_required_symbols(self, preconditions):
        return {p.fncIndex for p in preconditions}
    
    # Returns condition symbol name.
    def _get_condition_symbol_name(self, cond):
        # Caso 1: el propio objeto es un Predicate con atributo `name`
        name = getattr(cond, "name", None)
        if name is not None:
            return name
    
        # Caso 2: envoltorio que contiene un predicado interno
        predicate = getattr(cond, "predicate", None)
        if predicate is not None:
            pred_name = getattr(predicate, "name", None)
            if pred_name is not None:
                return pred_name
    
        # Caso 3: negación u otro nodo unario
        argument = getattr(cond, "argument", None)
        if argument is not None:
            return self._get_condition_symbol_name(argument)
    
        # Caso 4: fórmula con varios operandos
        operands = getattr(cond, "operands", None)
        if operands:
            for op in operands:
                op_name = self._get_condition_symbol_name(op)
                if op_name is not None:
                    return op_name
    
        return None
    
    # Creates grounded variables and numeric values from the initial state.
    def initInitialState(self):
        self.object_list = list(self.problem.objects)
        self.object_to_index = {
            getattr(obj, "name", str(obj)): i
            for i, obj in enumerate(self.object_list)
        }
    
        self.newValues = []
        self.auxValues = []
        self.valuesByFunction.clear()
    
        init_facts = list(self._iter_initial_facts())
    
        for fact in init_facts:
            self.createVariable(fact)
    
        self.numValues = 0
    
        for fact in init_facts:
            var_index = self.getVariableIndex(fact)
            var = self.gTask.variables[var_index]
    
            grounded_value = GroundedValue(
                time=self._fact_time(fact),
                value=self._get_fact_value_index(fact),
                numericValue=self._get_fact_numeric_value(fact),
            )
            var.initialValues.append(grounded_value)
    
            if not var.isNumeric:
                pv = ProgrammedValue(
                    index=self.numValues,
                    varIndex=var_index,
                    valueIndex=grounded_value.value,
                )
                self.numValues += 1
    
                self.newValues.append(pv)
                self.valuesByFunction[var.fncIndex].append(pv)
                self.gTask.reachedValues[var_index][grounded_value.value] = 0
    
        self.startNewValues = 0
        
    # Creates or retrieves a grounded variable for a fact.
    def createVariable(self, fact):
        fact_name = self.getVariableName(
            self._get_fact_function_key(fact),
            self._get_fact_parameter_signature(fact),
        )
    
        if fact_name not in self.variableIndex:
            v = GroundedVar(
                index=len(self.gTask.variables),
                fncIndex=self._get_fact_function_key(fact),
                isNumeric=self._fact_is_numeric(fact),
                params=self._get_fact_parameter_signature(fact),
                initialValues=[],
            )
    
            self.gTask.variables.append(v)
            self.variableIndex[fact_name] = v.index
    
            not_reached = None
    
            if v.isNumeric:
                self.gTask.reachedValues.append([0, not_reached])
            else:
                self.gTask.reachedValues.append([not_reached, not_reached])  # [FALSE, TRUE]
                
    # Formats the name of a grounded variable.
    def getVariableName(self, function, parameters):
        name = str(function)
        for p in parameters:
            name += " " + str(p)
        return name
        
    # Returns the grounded variable index for a fact.
    def getVariableIndex(self, fact):
        fact_name = self.getVariableName(
            self._get_fact_function_key(fact),
            self._get_fact_parameter_signature(fact),
        )
        return self.variableIndex[fact_name]
    
    # Continues binding operator parameters after indexed precondition matching.
    def groundRemainingParameters(self, op):
        pIndex = None
    
        for i in range(op.numParams):
            if len(op.paramValues[i]) == 0:
                pIndex = i
                break
    
        if pIndex is None:
            self.groundAction(op)
        else:
            compatible_objects = op.compatibleObjectsWithParam[pIndex]
    
            for obj_index in compatible_objects:
                op.paramValues[pIndex].append(obj_index)
                self.groundRemainingParameters(op)
                op.paramValues[pIndex].pop()
                
    # Creates one grounded action for the current operator parameter binding.
    def groundAction(self, op):
        a = GroundedAction(
            instantaneous=getattr(op.op, "instantaneous", True),
            isTIL=getattr(op.op, "isTIL", False),
            isGoal=getattr(op.op, "isGoal", False),
        )
        a.index = len(self.gTask.actions)
        a.name = op.op.name
    
        for i in range(op.numParams):
            a.parameters.append(op.paramValues[i][-1])
    
        if not getattr(op.op, "isGoal", False):
            param_names = [
                getattr(self.objects[idx], "name", str(self.objects[idx]))
                for idx in a.parameters
            ]
            name = self.getVariableName(a.name, param_names)
        
            if name in self.groundedActions:
                return
            self.groundedActions[name] = a.index
            
        if not self.checkEqualityConditions(op, a):
            return
        if not self.groundPreconditions(op, a):
            return
        if not self.groundEffects(op, a):
            return
        #print(a.to_string(self))
        for eff in a.effects:
            self.programNewValue(eff)
        
        if getattr(op.op, "isGoal", False):
            self.gTask.goals.append(a)
        else:
            self.gTask.actions.append(a)

    # Converts an effect into a programmed grounded value update.
    def programNewValue(self, eff):
        v = self.gTask.reachedValues[eff.varIndex]
    
        if eff.valueIndex >= len(v):
            v.extend([None] * (eff.valueIndex - len(v) + 1))
    
        if v[eff.valueIndex] is None:
            v[eff.valueIndex] = self.currentLevel + 1
            self.auxValues.append(
                ProgrammedValue(self.numValues, eff.varIndex, eff.valueIndex)
            )
            self.numValues += 1
            
    # Grounds all effects of an operator for one action instance.
    def groundEffects(self, op, a):
        if not self._ground_boolean_effects(op.effects, a.parameters, a.effects):
            return False
    
        if not self._ground_numeric_effects(op.numericEffects, a):
            return False
    
        return True
    
    # Grounds boolean effects.
    def _ground_boolean_effects(self, opEff, parameters, aEff):
        for eff in opEff:
            literal = eff.variable
    
            varIndex = self._get_variable_index_from_literal(literal, parameters)
            if varIndex is None:
                varIndex = self.createNewVariable(literal, parameters)
    
            value = (
                parameters[eff.value.index]
                if eff.value.type == TermType.TERM_PARAMETER
                else eff.value.index
            )
    
            addEffect = True
    
            for existing in aEff:
                if existing.varIndex == varIndex:
                    if existing.valueIndex != value:
                        if self._is_boolean_value(value) and self._is_boolean_value(existing.valueIndex):
                            if value == BOOL_FALSE:
                                existing.valueIndex = value
                                value = BOOL_TRUE
                        else:
                            return False
                    else:
                        addEffect = False
                        break
    
            if addEffect:
                aEff.append(GroundedCondition(varIndex=varIndex, valueIndex=value))
    
        return True
    
    # Checks whether boolean value.
    def _is_boolean_value(self, value):
        return value in (BOOL_FALSE, BOOL_TRUE)
    
    # Grounds numeric effects.
    def _ground_numeric_effects(self, opEff, a):
        for eff in opEff:
            if eff.variable is not None:
                var_index = self._get_or_create_grounded_numeric_variable(
                    eff.variable,
                    a.parameters,
                )
            else:
                var_index = eff.varIndex
    
            if var_index is None or var_index >= len(self.gTask.variables):
                return False
    
            exp = self.groundNumericExpression(eff.exp, a.parameters)
            if exp.type == GroundedNumericExpressionType.GE_UNDEFINED:
                return False
    
            n = GroundedNumericEffect(
                assignment=eff.assignment,
                varIndex=var_index,
                exp=exp,
            )
            a.numericEffects.append(n)
    
        return True
    
    # Checks equality constraints for the current action binding.
    def checkEqualityConditions(self, op, a):
        eq = getattr(op, "equality", [])
    
        for condition in eq:
            if condition.equal:
                if condition.value1.type == TermType.TERM_PARAMETER:
                    if condition.value2.type == TermType.TERM_PARAMETER:
                        if a.parameters[condition.value1.index] != a.parameters[condition.value2.index]:
                            return False
                    else:
                        if a.parameters[condition.value1.index] != condition.value2.index:
                            return False
                else:
                    if condition.value2.type == TermType.TERM_PARAMETER:
                        if condition.value1.index != a.parameters[condition.value2.index]:
                            return False
                    else:
                        if condition.value1.index != condition.value2.index:
                            return False
            else:
                if condition.value1.type == TermType.TERM_PARAMETER:
                    if condition.value2.type == TermType.TERM_PARAMETER:
                        if a.parameters[condition.value1.index] == a.parameters[condition.value2.index]:
                            return False
                    else:
                        if a.parameters[condition.value1.index] == condition.value2.index:
                            return False
                else:
                    if condition.value2.type == TermType.TERM_PARAMETER:
                        if condition.value1.index == a.parameters[condition.value2.index]:
                            return False
                    else:
                        if condition.value1.index == condition.value2.index:
                            return False
    
        return True

    # Grounds all preconditions for one action instance.
    def groundPreconditions(self, op, a):
        if not self._ground_boolean_preconditions(op.preconditions, a.parameters, a.conditions):
            return False
    
        if not self._ground_numeric_preconditions(op.numericPreconditions, a.parameters, a.numericConditions):
            return False
    
        return True
    
    # Grounds boolean preconditions.
    def _ground_boolean_preconditions(self, opCond, parameters, aCond):
        for cond in opCond:
            literal = Literal(
                fncIndex=cond.fncIndex,
                params=cond.params,
            )
    
            varIndex = self._get_variable_index_from_literal(literal, parameters)
            if varIndex is None:
                varIndex = self.createNewVariable(literal, parameters)
    
            value = (
                parameters[cond.value.index]
                if cond.value.type == TermType.TERM_PARAMETER
                else cond.value.index
            )
    
            aCond.append(GroundedCondition(varIndex=varIndex, valueIndex=value))
    
        return True
    
    # Creates a new grounded variable from a literal and parameter binding.
    def createNewVariable(self, literal, opParameters):
        v = GroundedVar(
            index=len(self.gTask.variables),
            fncIndex=literal.fncIndex,
            isNumeric=self._is_numeric_function_symbol(literal.fncIndex),
            params=[],
            initialValues=[],
        )
    
        for term in literal.params:
            if term.type == TermType.TERM_PARAMETER:
                v.params.append(opParameters[term.index])
            else:
                v.params.append(term.index)
    
        self.gTask.variables.append(v)
    
        name = self.getVariableName(v.fncIndex, v.params)
        self.variableIndex[name] = v.index
    
        not_reached = None
        if v.isNumeric:
            self.gTask.reachedValues.append([0, not_reached])
        else:
            # Booleano: [FALSE, TRUE]
            self.gTask.reachedValues.append([not_reached, not_reached])    
        return v.index
    
    # Returns variable index from literal.
    def _get_variable_index_from_literal(self, literal, opParameters):
        params = []
        for term in literal.params:
            if term.type == TermType.TERM_PARAMETER:
                params.append(opParameters[term.index])
            else:
                params.append(term.index)
    
        name = self.getVariableName(literal.fncIndex, params)
        return self.variableIndex.get(name)
    
    # Checks whether numeric function symbol.
    def _is_numeric_function_symbol(self, fncIndex):
        for fn in getattr(self.domain, "functions", []):
            if getattr(fn, "name", None) == fncIndex:
                return True
        return False
    
    # Grounds numeric preconditions.
    def _ground_numeric_preconditions(self, opCond, parameters, aCond):
        for cond in opCond:
            c = GroundedNumericCondition(comparator=cond.comparator, terms=[])
    
            for term in cond.terms:
                e = self.groundNumericExpression(term, parameters)
                if e.type == GroundedNumericExpressionType.GE_UNDEFINED:
                    return False
                c.terms.append(e)
    
            aCond.append(c)
    
        return True
    
    # Grounds a parsed numeric expression into the internal representation.
    def groundNumericExpression(self, exp, parameters):
        if exp.type == GroundedNumericExpressionType.GE_VAR:
            if exp.variable is None:
                if exp.index is None or exp.index >= len(self.gTask.variables):
                    return GroundedNumericExpression(type=GroundedNumericExpressionType.GE_UNDEFINED)
                return exp
    
            var_index = self._get_or_create_grounded_numeric_variable(exp.variable, parameters)
            return GroundedNumericExpression(
                type=GroundedNumericExpressionType.GE_VAR,
                index=var_index,
            )
    
        if exp.type in {
            GroundedNumericExpressionType.GE_NUMBER,
            GroundedNumericExpressionType.GE_OBJECT,
            GroundedNumericExpressionType.GE_DURATION,
            GroundedNumericExpressionType.GE_CONTROL_VAR,
        }:
            return exp
    
        if exp.type in {
            GroundedNumericExpressionType.GE_SUM,
            GroundedNumericExpressionType.GE_SUB,
            GroundedNumericExpressionType.GE_DIV,
            GroundedNumericExpressionType.GE_MUL,
            GroundedNumericExpressionType.GE_SHARP_T,
        }:
            grounded_terms = []
            for sub in exp.terms:
                e = self.groundNumericExpression(sub, parameters)
                if e.type == GroundedNumericExpressionType.GE_UNDEFINED:
                    return GroundedNumericExpression(type=GroundedNumericExpressionType.GE_UNDEFINED)
                grounded_terms.append(e)
    
            return GroundedNumericExpression(
                type=exp.type,
                terms=grounded_terms,
            )
    
        return GroundedNumericExpression(type=GroundedNumericExpressionType.GE_UNDEFINED)

    # Checks whether equality condition.
    def _is_equality_condition(self, cond):
        return cond.__class__.__name__ in {"EqualTo", "NotEqualTo"}
    
    # Checks whether term equality condition.
    def _is_term_equality_condition(self, cond):
        if not self._is_equality_condition(cond):
            return False
    
        left, right = self._get_binary_operands(cond)
    
        # Si alguno es función numérica o valor numérico, no es equality de objetos
        if isinstance(left, (NumericFunction, NumericValue)):
            return False
        if isinstance(right, (NumericFunction, NumericValue)):
            return False
    
        return True

    # Handles numeric function to numeric ref.
    def _numeric_function_to_numeric_ref(self, func, action):
        param_index = self._build_action_param_index(action)

        params = []
        for t in func.terms:
            if isinstance(t, Variable) and t.name in param_index:
                params.append(Term(TermType.TERM_PARAMETER, param_index[t.name]))
            else:
                obj_idx = self._term_to_index_or_name(t)
                if not isinstance(obj_idx, int):
                    raise ValueError(f"No se pudo resolver a objeto constante: {t!r}")
                params.append(Term(TermType.TERM_CONSTANT, obj_idx))

        return NumericVariableRef(
            fncIndex=func.name,
            params=params,
        )
    
    # Handles numeric expression to grounded.
    def _numeric_expression_to_grounded(self, expr, action):
        cls = expr.__class__.__name__
    
        if isinstance(expr, NumericValue):
            return GroundedNumericExpression(
                type=GroundedNumericExpressionType.GE_NUMBER,
                value=float(expr.value),
            )
    
        if isinstance(expr, NumericFunction):
            return GroundedNumericExpression(
                type=GroundedNumericExpressionType.GE_VAR,
                variable=self._numeric_function_to_numeric_ref(expr, action),
            )
    
        if hasattr(expr, "operands"):
            subterms = [self._numeric_expression_to_grounded(x, action) for x in expr.operands]
    
            if cls == "Sum":
                t = GroundedNumericExpressionType.GE_SUM
            elif cls == "Subtraction":
                t = GroundedNumericExpressionType.GE_SUB
            elif cls == "Division":
                t = GroundedNumericExpressionType.GE_DIV
            elif cls == "Multiplication":
                t = GroundedNumericExpressionType.GE_MUL
            else:
                raise NotImplementedError(f"Expresión numérica no soportada: {expr!r}")
    
            return GroundedNumericExpression(type=t, terms=subterms)
    
        raise NotImplementedError(f"Expresión numérica no soportada: {expr!r}")
    
    # Returns or create grounded numeric variable.
    def _get_or_create_grounded_numeric_variable(self, var_ref, parameters):
        grounded_params = []
        for term in var_ref.params:
            if term.type == TermType.TERM_PARAMETER:
                grounded_params.append(parameters[term.index])
            else:
                grounded_params.append(term.index)
    
        name = self.getVariableName(var_ref.fncIndex, grounded_params)
        var_index = self.variableIndex.get(name)
        if var_index is not None:
            return var_index
    
        v = GroundedVar(
            index=len(self.gTask.variables),
            fncIndex=var_ref.fncIndex,
            isNumeric=True,
            params=grounded_params,
            initialValues=[],
        )
        self.gTask.variables.append(v)
        self.variableIndex[name] = v.index
        self.gTask.reachedValues.append([0, None])
        return v.index
    
    # Swaps grounding search levels while matching operator preconditions.
    def swapLevels(self):
        for pv in self.auxValues:
            fnc_index = self.gTask.variables[pv.varIndex].fncIndex
            self.valuesByFunction[fnc_index].append(pv)
    
        self.newValues, self.auxValues = self.auxValues, self.newValues
        self.auxValues.clear()
        
    # Starts matching a programmed value against candidate operator preconditions.
    def match(self, pv):
        fnc_index = self.gTask.variables[pv.varIndex].fncIndex
        required_ops = self.opRequireFunction[fnc_index]
    
        for op in required_ops:
            prec_index = -1
    
            while True:
                prec_index = self.matches(op, pv.varIndex, pv.valueIndex, prec_index + 1)
                if prec_index == -1:
                    break
    
                op.newValueIndex = pv.index
                self.stackParameters(op, prec_index, pv.varIndex, pv.valueIndex)
                self.completeMatch(op, 0)
                self.unstackParameters(op, prec_index)
                
    # Pushes parameter bindings produced by a precondition match.
    def stackParameters(self, op, precIndex, varIndex, valueIndex):
        prec = op.preconditions[precIndex]
        v = self.gTask.variables[varIndex]
    
        for i in range(len(v.params)):
            term = prec.params[i]
            if term.type == TermType.TERM_PARAMETER:
                op.paramValues[term.index].append(v.params[i])
    
        if prec.value.type == TermType.TERM_PARAMETER:
            op.paramValues[prec.value.index].append(valueIndex)
    
        prec.grounded = True
        
    # Removes parameter bindings for a backtracked precondition match.
    def unstackParameters(self, op, precIndex):
        prec = op.preconditions[precIndex]
    
        for term in prec.params:
            if term.type == TermType.TERM_PARAMETER:
                op.paramValues[term.index].pop()
    
        if prec.value.type == TermType.TERM_PARAMETER:
            op.paramValues[prec.value.index].pop()
    
        prec.grounded = False
        
    # Checks whether a variable-value pair can match an operator precondition.
    def matches(self, op, varIndex, valueIndex, startIndex):
        fncIndex = self.gTask.variables[varIndex].fncIndex
    
        for i in range(startIndex, len(op.preconditions)):
            p = op.preconditions[i]
            if (not p.grounded
                    and p.fncIndex == fncIndex
                    and self.precMatches(op, p, varIndex, valueIndex)):
                return i
    
        return -1
    
    # Checks whether one operator precondition matches a grounded value.
    def precMatches(self, op, p, varIndex, valueIndex):
        v = self.gTask.variables[varIndex]
    
        # Check the parameters
        for i in range(len(v.params)):
            paramIndex = p.params[i].index
    
            if p.params[i].type == TermType.TERM_PARAMETER:
                paramValues = op.paramValues[paramIndex]
    
                if len(paramValues) == 0:
                    if not self.objectIsCompatible(
                        v.params[i],
                        self._get_parameter_types(op.op.parameters[paramIndex]),
                    ):
                        return False
                else:
                    if paramValues[-1] != v.params[i]:
                        return False
            else:
                if paramIndex != v.params[i]:
                    return False
    
        # Check the value
        paramIndex = p.value.index
    
        if p.value.type == TermType.TERM_PARAMETER:
            paramValues = op.paramValues[paramIndex]
    
            if len(paramValues) == 0:
                return self.objectIsCompatible(
                    valueIndex,
                    self._get_parameter_types(op.op.parameters[paramIndex]),
                )
            else:
                return paramValues[-1] == valueIndex
        else:
            return valueIndex == paramIndex
    
    # Finishes matching remaining preconditions and grounds actions.
    def completeMatch(self, op, precIndex):
        p = None
    
        while precIndex < len(op.preconditions):
            p = op.preconditions[precIndex]
    
            if not p.grounded:
                if p.value.type != TermType.TERM_PARAMETER and p.value.index == BOOL_FALSE:
                    p.grounded = True
                else:
                    break
    
            precIndex += 1
    
        if precIndex >= len(op.preconditions):
            self.groundRemainingParameters(op)
        else:
            vf = self.valuesByFunction[p.fncIndex]
    
            for pv in vf:
                if ((pv.index < self.startNewValues or pv.index >= op.newValueIndex)
                        and self.precMatches(op, p, pv.varIndex, pv.valueIndex)):
                    self.stackParameters(op, precIndex, pv.varIndex, pv.valueIndex)
                    self.completeMatch(op, precIndex + 1)
                    self.unstackParameters(op, precIndex)
        
    # Builds action param index.
    def _build_action_param_index(self, action):
        return {param.name: i for i, param in enumerate(action.parameters)}

    # Converts to grounder term.
    def _term_to_grounder_term(self, term, param_index):
        if isinstance(term, Variable) and term.name in param_index:
            return Term(TermType.TERM_PARAMETER, param_index[term.name])
    
        if isinstance(term, Constant):
            idx = self.object_to_index.get(term.name)
            if idx is None:
                raise ValueError(f"Constante no encontrada entre los objetos: {term}")
            return Term(TermType.TERM_CONSTANT, idx)
    
        if hasattr(term, "name"):
            idx = self.object_to_index.get(term.name)
            if idx is not None:
                return Term(TermType.TERM_CONSTANT, idx)
    
        raise ValueError(f"No puedo convertir el término a Term: {term!r}")
        
    # Returns fact function key.
    def _get_fact_function_key(self, fact):
        # Caso 1: predicado/función atómica con name propio
        name = getattr(fact, "name", None)
        if name is not None:
            return name

        # Caso 2: envoltorio con predicate interno
        predicate = getattr(fact, "predicate", None)
        if predicate is not None:
            pred_name = getattr(predicate, "name", None)
            if pred_name is not None:
                return pred_name

        # Caso 3: igualdades, p. ej. EqualTo((NumericFunction(...), NumericValue(...)))
        operands = getattr(fact, "operands", None)
        if operands:
            lhs = operands[0]

            lhs_name = getattr(lhs, "name", None)
            if lhs_name is not None:
                return lhs_name

            lhs_symbol = getattr(lhs, "symbol", None)
            if lhs_symbol is not None:
                lhs_symbol_name = getattr(lhs_symbol, "name", None)
                if lhs_symbol_name is not None:
                    return lhs_symbol_name
                return str(lhs_symbol)

            # Último recurso: intentar parsear el repr/str
            lhs_str = str(lhs)
            if "(" in lhs_str:
                return lhs_str.split("(", 1)[0].strip()

        raise ValueError(f"No puedo extraer la función/predicado de {fact!r}")
        
    # Returns fact parameter signature.
    def _get_fact_parameter_signature(self, fact):
        terms = self._get_fact_terms(fact)
        return [self._term_to_index_or_name(t) for t in terms]

    # Returns fact terms.
    def _get_fact_terms(self, fact):
        # Caso directo
        terms = getattr(fact, "terms", None)
        if terms is not None:
            return list(terms)

        # Caso igualdad: mirar el lado izquierdo
        operands = getattr(fact, "operands", None)
        if operands:
            lhs = operands[0]
            lhs_terms = getattr(lhs, "terms", None)
            if lhs_terms is not None:
                return list(lhs_terms)

        return []

    # Converts to index or name.
    def _term_to_index_or_name(self, term):
        name = getattr(term, "name", None)
        if name is not None and name in self.object_to_index:
            return self.object_to_index[name]
        if name is not None:
            return name
        return str(term)

    # Extracts fact is numeric information.
    def _fact_is_numeric(self, fact):
        operands = getattr(fact, "operands", None)
        if operands and len(operands) == 2:
            rhs = operands[1]
            return rhs.__class__.__name__ == "NumericValue"
        return False


    # Returns fact numeric value.
    def _get_fact_numeric_value(self, fact):
        operands = getattr(fact, "operands", None)
        if operands and len(operands) == 2:
            rhs = operands[1]

            value = getattr(rhs, "value", None)
            if value is not None:
                return float(value)

            # respaldo por si la clase usa otro atributo interno
            try:
                return float(str(rhs))
            except ValueError:
                pass

        return 0.0

    # Iterates over initial facts.
    def _iter_initial_facts(self):
        return self.problem.init

    # Extracts fact time information.
    def _fact_time(self, fact):
        return getattr(fact, "time", 0.0)

    # Returns fact value index.
    def _get_fact_value_index(self, fact):
        if self._fact_is_numeric(fact):
            return 0  # no se usa realmente en numéricos
        return BOOL_TRUE

    # Converts to opfluent.
    def _predicate_to_opfluent(self, pred, param_index, truth_value):
        literal = Literal(
            fncIndex=pred.name,
            params=[self._term_to_grounder_term(t, param_index) for t in pred.terms],
        )
        value = Term(TermType.TERM_CONSTANT, truth_value)
        return OpFluent(variable=literal, value=value)

    # Converts to opfluent.
    def _condition_to_opfluent(self, cond, action):
        param_index = self._build_action_param_index(action)
    
        if isinstance(cond, Predicate):
            return self._predicate_to_opfluent(cond, param_index, BOOL_TRUE)
    
        if isinstance(cond, Not):
            arg = cond.argument
            if isinstance(arg, Predicate):
                return self._predicate_to_opfluent(arg, param_index, BOOL_FALSE)
            raise NotImplementedError(f"Negación no soportada en precondición: {cond!r}")
    
        raise NotImplementedError(f"Condición no soportada para convertir a OpFluent: {cond!r}")