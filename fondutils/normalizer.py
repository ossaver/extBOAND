from pddl.action import Action
from pddl.logic.base import OneOf, Not, And
from pddl.logic.effects import When
from pddl.logic.predicates import Predicate
from pddl.logic.functions import Increase

from itertools import product, chain

DEBUG = False

# Normalizes action effects before determinization.
def normalize(op):

    effs = flatten(op.effect)

    if len(effs) == 1:
        eff = effs[0]
    else:
        # Normalize to wrap every operand of an OneOf in an And
        for i in range(len(effs)):
            if not isinstance(effs[i], And):
                effs[i] = And(effs[i])
        
        # Compress one level of nested And on the outcomes
        new_outcomes = []
        for outcome in effs:
            if isinstance(outcome, And):
                new_operands = []
                for operand in outcome.operands:
                    if isinstance(operand, And):
                        new_operands.extend(operand.operands)
                    else:
                        new_operands.append(operand)
                new_outcomes.append(And(*new_operands))
            else:
                new_outcomes.append(outcome)

        eff = OneOf(*new_outcomes)

    return Action(
        name=op.name,
        parameters=op.parameters,
        precondition=op.precondition,
        effect=eff)

# Flattens nested conjunctions in an effect expression.
def flatten(eff):
    return _flatten(eff)

# Combines flattened effect lists into normalized conjunction alternatives.
def combine(eff_lists):
    combos = list(product(*eff_lists))
    combined_oneofs = []

    for choice in combos:
        flat_choice = []
        for x in choice:
            if isinstance(x, list):
                flat_choice.extend(x)
            else:
                flat_choice.append(x)

        flat_choice = [
            x for x in flat_choice
            if not (isinstance(x, And) and len(x.operands) == 0)
        ]

        combined_oneofs.append(And(*flat_choice) if flat_choice else And())

    if DEBUG:
        print("\nCombining:\n%s" % '\n'.join(map(str, eff_lists)))
        print("Result: %s\n" % combined_oneofs)

    return combined_oneofs

# Handles the internal flatten step.
def _flatten(eff):

    if DEBUG:
        print("Flattening %s" % str(eff))

    if isinstance(eff, And):
        if len(eff.operands) == 0:
            return [eff]
        else:
            return combine(list(map(_flatten, eff.operands)))

    elif isinstance(eff, OneOf):
        return list(chain(*(list(map(_flatten, eff.operands)))))

    elif isinstance(eff, When):
        return [When(eff.condition, res) for res in _flatten(eff.effect)]

    # Default atomic cases
    elif isinstance(eff, Not):
        return [eff]

    elif isinstance(eff, Predicate):
        return [eff]

    elif isinstance(eff, Increase):
        return [eff]
    
    else:
        if DEBUG:
            print("Base: %s" % str(eff))
        raise ValueError("Unexpected effect type: %s" % type(eff))