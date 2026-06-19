(define (domain icylake)

(:requirements
    :strips
    :typing
    :non-deterministic
    :fluents
	:action-costs
)

(:types
    tile reward - object
    ice wall pit - tile
)

(:predicates
    (at ?t - tile)
    (left-of ?l - tile ?r - tile)
    (down-of ?d - tile ?u - tile)
    (reward-position ?r - reward ?t - ice)
	(has-reward ?r - reward)
)

(:functions
    (total-cost)
	(budget)
	(normal-step-cost)
	(slip-step-cost)
)

(:action collect-reward
    :parameters (?r - reward ?t - ice)
    :precondition (and
        (at ?t)
        (reward-position ?r ?t)
    )
    :effect (and
        (not (reward-position ?r ?t))
        (has-reward ?r)
    )
)

(:action left
    :parameters (?src - ice ?dst1 - ice ?dst2 - ice)
    :precondition (and
        (at ?src)
        (left-of ?dst1 ?src)
        (left-of ?dst2 ?dst1)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst1)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?dst2)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action left-to-wall
    :parameters (?src - ice ?dst - ice ?w - wall)
    :precondition (and
        (at ?src)
        (left-of ?dst ?src)
        (left-of ?w ?dst)
    )
    :effect (and
        (not (at ?src))
        (at ?dst)
        (increase (total-cost) (normal-step-cost))
    )
)

(:action left-to-pit
    :parameters (?src - ice ?dst - ice ?p - pit)
    :precondition (and
        (at ?src)
        (left-of ?dst ?src)
        (left-of ?p ?dst)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?p)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action right
    :parameters (?src - ice ?dst1 - ice ?dst2 - ice)
    :precondition (and
        (at ?src)
        (left-of ?src ?dst1)
        (left-of ?dst1 ?dst2)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst1)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?dst2)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action right-to-wall
    :parameters (?src - ice ?dst - ice ?w - wall)
    :precondition (and
        (at ?src)
        (left-of ?src ?dst)
        (left-of ?dst ?w)
    )
    :effect (and
        (not (at ?src))
        (at ?dst)
        (increase (total-cost) (normal-step-cost))
    )
)

(:action right-to-pit
    :parameters (?src - ice ?dst - ice ?p - pit)
    :precondition (and
        (at ?src)
        (left-of ?src ?dst)
        (left-of ?dst ?p)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?p)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action down
    :parameters (?src - ice ?dst1 - ice ?dst2 - ice)
    :precondition (and
        (at ?src)
        (down-of ?dst1 ?src)
        (down-of ?dst2 ?dst1)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst1)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?dst2)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action down-to-wall
    :parameters (?src - ice ?dst - ice ?w - wall)
    :precondition (and
        (at ?src)
        (down-of ?dst ?src)
        (down-of ?w ?dst)
    )
    :effect (and
        (not (at ?src))
        (at ?dst)
        (increase (total-cost) (normal-step-cost))
    )
)

(:action down-to-pit
    :parameters (?src - ice ?dst - ice ?p - pit)
    :precondition (and
        (at ?src)
        (down-of ?dst ?src)
        (down-of ?p ?dst)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?p)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action up
    :parameters (?src - ice ?dst1 - ice ?dst2 - ice)
    :precondition (and
        (at ?src)
        (down-of ?src ?dst1)
        (down-of ?dst1 ?dst2)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst1)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?dst2)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

(:action up-to-wall
    :parameters (?src - ice ?dst - ice ?w - wall)
    :precondition (and
        (at ?src)
        (down-of ?src ?dst)
        (down-of ?dst ?w)
    )
    :effect (and
        (not (at ?src))
        (at ?dst)
        (increase (total-cost) (normal-step-cost))
    )
)

(:action up-to-pit
    :parameters (?src - ice ?dst - ice ?p - pit)
    :precondition (and
        (at ?src)
        (down-of ?src ?dst)
        (down-of ?dst ?p)
    )
    :effect (and
        (not (at ?src))
        (oneof
            (and
                (at ?dst)
                (increase (total-cost) (normal-step-cost))
            )
            (and
                (at ?p)
                (increase (total-cost) (slip-step-cost))
            )
        )
    )
)

)