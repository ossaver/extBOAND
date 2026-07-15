(define (domain islands)
    (:requirements :strips :typing)
    (:types
        location monkey - object
    )
    (:predicates (bridge-clear) (bridge-drop-location ?loc - location)  (bridge-occupied) (bridge-road ?from - location ?to - location)  (monkey-at ?m - monkey ?loc - location)  (monkey-on-bridge ?m - monkey)  (person-alive) (person-at ?loc - location)  (road ?from - location ?to - location)  (swim-road ?from - location ?to - location))
    (:action climb-bridge
        :parameters (?m - monkey ?loc - location)
        :precondition (and (bridge-clear) (monkey-at ?m ?loc))
        :effect (and (not (monkey-at ?m ?loc)) (monkey-on-bridge ?m) (not (bridge-clear)) (bridge-occupied))
    )
     (:action leave-bridge
        :parameters (?m - monkey ?loc - location)
        :precondition (and (bridge-occupied) (monkey-on-bridge ?m) (bridge-drop-location ?loc))
        :effect (and (monkey-at ?m ?loc) (not (monkey-on-bridge ?m)) (not (bridge-occupied)) (bridge-clear))
    )
     (:action move-monkey
        :parameters (?from - location ?to - location ?m - monkey)
        :precondition (and (monkey-at ?m ?from) (road ?from ?to))
        :effect (and (not (monkey-at ?m ?from)) (monkey-at ?m ?to))
    )
     (:action move-person
        :parameters (?from - location ?to - location)
        :precondition (and (person-at ?from) (road ?from ?to) (person-alive))
        :effect (and (person-at ?to) (not (person-at ?from)))
    )
     (:action swim_DETDUP_1
        :parameters (?from - location ?to - location)
        :precondition (and (person-at ?from) (swim-road ?from ?to) (person-alive))
        :effect (and (not (person-at ?from)) (person-at ?to))
    )
     (:action swim_DETDUP_2
        :parameters (?from - location ?to - location)
        :precondition (and (person-at ?from) (swim-road ?from ?to) (person-alive))
        :effect (and (not (person-at ?from)) (not (person-alive)))
    )
     (:action walk-on-bridge
        :parameters (?from - location ?to - location)
        :precondition (and (person-at ?from) (bridge-road ?from ?to) (bridge-clear) (person-alive))
        :effect (and (not (person-at ?from)) (person-at ?to))
    )
)
