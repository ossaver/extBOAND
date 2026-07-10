(define (problem FR_1_8)
 (:domain first-response)
 (:objects  l1  - location
	    f1 - fire_unit
	    v1 v2 v3 v4 v5 v6 v7 v8 - victim
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
     (fire l1)
     (victim-at v5 l1)
     (victim-status v5 hurt)
     (fire l1)
     (victim-at v6 l1)
     (victim-status v6 hurt)
     (fire l1)
     (victim-at v7 l1)
     (victim-status v7 dying)
     (fire l1)
     (victim-at v8 l1)
     (victim-status v8 dying)
	;;map info
	(adjacent l1 l1)
	(fire-unit-at f1 l1)
	(medical-unit-at m1 l1)
	
   (= (total-cost) 0)
   )
  (:utility
     (= (nfire l1) 24)
     (= (victim-status v1 healthy) 32)
     (= (victim-status v2 healthy) 16)
     (= (victim-status v3 healthy) 48)
     (= (victim-status v4 healthy) 4)
     (= (victim-status v5 healthy) 13)
     (= (victim-status v6 healthy) 4)
     (= (victim-status v7 healthy) 48)
     (= (victim-status v8 healthy) 31)
 )
 
(:bound 10)
)
