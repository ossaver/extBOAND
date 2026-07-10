(define (problem FR_1_4)
 (:domain first-response)
 (:objects  l1  - location
	    f1 - fire_unit
	    v1 v2 v3 v4 - victim
	    m1 - medical_unit
)
 (:init 
	;;strategic locations
     (hospital l1)
     (water-at l1)
	;;disaster info
     (fire l1)
     (victim-at v1 l1)
     (victim-status v1 hurt)
     (fire l1)
     (victim-at v2 l1)
     (victim-status v2 hurt)
     (fire l1)
     (victim-at v3 l1)
     (victim-status v3 dying)
     (fire l1)
     (victim-at v4 l1)
     (victim-status v4 dying)
	;;map info
	(adjacent l1 l1)
	(fire-unit-at f1 l1)
	(medical-unit-at m1 l1)
	
   (= (total-cost) 0)
   )
  (:utility
     (= (nfire l1) 42)
     (= (victim-status v1 healthy) 4)
     (= (victim-status v2 healthy) 41)
     (= (victim-status v3 healthy) 3)
     (= (victim-status v4 healthy) 3)
 )
 
(:bound 6)
)
