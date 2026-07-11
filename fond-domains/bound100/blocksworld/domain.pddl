;; FOND version of Blocksworld from FOND track in 2008 IPC-6
;; Basically, it is the same domain as the one in the probabilistic track but with (oneof) instead of probabilities
;; https://ipc08.icaps-conference.org/probabilistic/wiki/index.php/Results.html#Fully_Observable_Non-Deterministic_.28FOND.29_track
(define (domain blocks-domain)
(:requirements
    :strips
    :typing
    :equality
    :non-deterministic
    :fluents
	:action-costs
)
  (:types
    block
  )
  (:predicates
    (holding ?b - block)
    (emptyhand)
    (on-table ?b - block)
    (on ?b1 ?b2 - block)
    (clear ?b - block)
  )

(:functions
    (total-cost)
)
  (:action pick-up
    :parameters (?b1 ?b2 - block)
    :precondition (and (not (= ?b1 ?b2)) (emptyhand) (clear ?b1) (on ?b1 ?b2))
    :effect (and (oneof
      (and (holding ?b1) (clear ?b2) (not (emptyhand)) (not (clear ?b1)) (not (on ?b1 ?b2)))
      (and (clear ?b2) (on-table ?b1) (not (on ?b1 ?b2)))) (increase (total-cost) 1))
  )
  (:action pick-up-from-table
    :parameters (?b - block)
    :precondition (and (emptyhand) (clear ?b) (on-table ?b))
    :effect (and (oneof
      (and)
      (and (holding ?b) (not (emptyhand)) (not (on-table ?b)))) (increase (total-cost) 1))
  )
  (:action put-on-block
    :parameters (?b1 ?b2 - block)
    :precondition (and (holding ?b1) (clear ?b2))
    :effect (and (oneof
      (and (on ?b1 ?b2) (emptyhand) (clear ?b1) (not (holding ?b1)) (not (clear ?b2)))
      (and (on-table ?b1) (emptyhand) (clear ?b1) (not (holding ?b1)))) (increase (total-cost) 1))
  )
  (:action put-down
    :parameters (?b - block)
    :precondition (holding ?b)
    :effect (and (on-table ?b) (emptyhand) (clear ?b) (not (holding ?b))
      (increase (total-cost) 1))
  )
  (:action pick-tower
    :parameters (?b1 ?b2 ?b3 - block)
    :precondition (and (emptyhand) (on ?b1 ?b2) (on ?b2 ?b3))
    :effect (and (oneof
      (and)
      (and (holding ?b2) (clear ?b3) (not (emptyhand)) (not (on ?b2 ?b3)))) (increase (total-cost) 1))
  )
  (:action put-tower-on-block
    :parameters (?b1 ?b2 ?b3 - block)
    :precondition (and (holding ?b2) (on ?b1 ?b2) (clear ?b3))
    :effect (and (oneof
      (and (on ?b2 ?b3) (emptyhand) (not (holding ?b2)) (not (clear ?b3)))
      (and (on-table ?b2) (emptyhand) (not (holding ?b2)))) (increase (total-cost) 1))
  )
  (:action put-tower-down
    :parameters (?b1 ?b2 - block)
    :precondition (and (holding ?b2) (on ?b1 ?b2))
    :effect (and (on-table ?b2) (emptyhand) (not (holding ?b2))
      (increase (total-cost) 1))
  )
)
