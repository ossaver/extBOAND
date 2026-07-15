(define (problem icylake-p10)
  (:domain icylake)

  (:objects
    upperwall-0 - wall upperwall-1 - wall upperwall-2 - wall upperwall-3 - wall upperwall-4 - wall upperwall-5 - wall upperwall-6 - wall upperwall-7 - wall
    leftwall-7 - wall tile_0_7 - ice tile_1_7 - ice tile_2_7 - ice tile_3_7 - ice tile_4_7 - ice tile_5_7 - ice tile_6_7 - ice tile_7_7 - ice rightwall-7 - wall
    leftwall-6 - wall tile_0_6 - ice tile_1_6 - ice tile_2_6 - ice tile_3_6 - ice tile_4_6 - wall tile_5_6 - ice tile_6_6 - wall tile_7_6 - pit rightwall-6 - wall
    leftwall-5 - wall tile_0_5 - ice tile_1_5 - ice tile_2_5 - wall tile_3_5 - ice tile_4_5 - ice tile_5_5 - ice tile_6_5 - ice tile_7_5 - ice rightwall-5 - wall
    leftwall-4 - wall tile_0_4 - ice tile_1_4 - ice tile_2_4 - pit tile_3_4 - ice tile_4_4 - ice tile_5_4 - ice tile_6_4 - wall tile_7_4 - ice rightwall-4 - wall
    leftwall-3 - wall tile_0_3 - ice tile_1_3 - ice tile_2_3 - pit tile_3_3 - pit tile_4_3 - ice tile_5_3 - ice tile_6_3 - ice tile_7_3 - ice rightwall-3 - wall
    leftwall-2 - wall tile_0_2 - ice tile_1_2 - ice tile_2_2 - ice tile_3_2 - ice tile_4_2 - ice tile_5_2 - ice tile_6_2 - ice tile_7_2 - ice rightwall-2 - wall
    leftwall-1 - wall tile_0_1 - ice tile_1_1 - ice tile_2_1 - ice tile_3_1 - ice tile_4_1 - ice tile_5_1 - ice tile_6_1 - ice tile_7_1 - wall rightwall-1 - wall
    leftwall-0 - wall tile_0_0 - ice tile_1_0 - ice tile_2_0 - ice tile_3_0 - ice tile_4_0 - ice tile_5_0 - pit tile_6_0 - ice tile_7_0 - ice rightwall-0 - wall
    bottomwall-0 - wall bottomwall-1 - wall bottomwall-2 - wall bottomwall-3 - wall bottomwall-4 - wall bottomwall-5 - wall bottomwall-6 - wall bottomwall-7 - wall
    first-aid-kit-1 - reward first-aid-kit-2 - reward first-aid-kit-3 - reward first-aid-kit-4 - reward diamond-1 - reward diamond-2 - reward diamond-3 - reward diamond-4 - reward
  )

  (:init
    (at tile_0_7)
    (reward-position first-aid-kit-1 tile_2_1)
    (reward-position first-aid-kit-2 tile_1_1)
    (reward-position first-aid-kit-3 tile_5_7)
    (reward-position first-aid-kit-4 tile_6_5)
    (reward-position diamond-1 tile_5_1)
    (reward-position diamond-2 tile_6_0)
    (reward-position diamond-3 tile_1_6)
    (reward-position diamond-4 tile_0_4)

    (left-of leftwall-7 tile_0_7) (left-of tile_0_7 tile_1_7) (left-of tile_1_7 tile_2_7) (left-of tile_2_7 tile_3_7) (left-of tile_3_7 tile_4_7) (left-of tile_4_7 tile_5_7) (left-of tile_5_7 tile_6_7) (left-of tile_6_7 tile_7_7) (left-of tile_7_7 rightwall-7)
    (left-of leftwall-6 tile_0_6) (left-of tile_0_6 tile_1_6) (left-of tile_1_6 tile_2_6) (left-of tile_2_6 tile_3_6) (left-of tile_3_6 tile_4_6) (left-of tile_4_6 tile_5_6) (left-of tile_5_6 tile_6_6) (left-of tile_6_6 tile_7_6) (left-of tile_7_6 rightwall-6)
    (left-of leftwall-5 tile_0_5) (left-of tile_0_5 tile_1_5) (left-of tile_1_5 tile_2_5) (left-of tile_2_5 tile_3_5) (left-of tile_3_5 tile_4_5) (left-of tile_4_5 tile_5_5) (left-of tile_5_5 tile_6_5) (left-of tile_6_5 tile_7_5) (left-of tile_7_5 rightwall-5)
    (left-of leftwall-4 tile_0_4) (left-of tile_0_4 tile_1_4) (left-of tile_1_4 tile_2_4) (left-of tile_2_4 tile_3_4) (left-of tile_3_4 tile_4_4) (left-of tile_4_4 tile_5_4) (left-of tile_5_4 tile_6_4) (left-of tile_6_4 tile_7_4) (left-of tile_7_4 rightwall-4)
    (left-of leftwall-3 tile_0_3) (left-of tile_0_3 tile_1_3) (left-of tile_1_3 tile_2_3) (left-of tile_2_3 tile_3_3) (left-of tile_3_3 tile_4_3) (left-of tile_4_3 tile_5_3) (left-of tile_5_3 tile_6_3) (left-of tile_6_3 tile_7_3) (left-of tile_7_3 rightwall-3)
    (left-of leftwall-2 tile_0_2) (left-of tile_0_2 tile_1_2) (left-of tile_1_2 tile_2_2) (left-of tile_2_2 tile_3_2) (left-of tile_3_2 tile_4_2) (left-of tile_4_2 tile_5_2) (left-of tile_5_2 tile_6_2) (left-of tile_6_2 tile_7_2) (left-of tile_7_2 rightwall-2)
    (left-of leftwall-1 tile_0_1) (left-of tile_0_1 tile_1_1) (left-of tile_1_1 tile_2_1) (left-of tile_2_1 tile_3_1) (left-of tile_3_1 tile_4_1) (left-of tile_4_1 tile_5_1) (left-of tile_5_1 tile_6_1) (left-of tile_6_1 tile_7_1) (left-of tile_7_1 rightwall-1)
    (left-of leftwall-0 tile_0_0) (left-of tile_0_0 tile_1_0) (left-of tile_1_0 tile_2_0) (left-of tile_2_0 tile_3_0) (left-of tile_3_0 tile_4_0) (left-of tile_4_0 tile_5_0) (left-of tile_5_0 tile_6_0) (left-of tile_6_0 tile_7_0) (left-of tile_7_0 rightwall-0)

    (down-of tile_0_7 upperwall-0) (down-of tile_0_6 tile_0_7) (down-of tile_0_5 tile_0_6) (down-of tile_0_4 tile_0_5) (down-of tile_0_3 tile_0_4) (down-of tile_0_2 tile_0_3) (down-of tile_0_1 tile_0_2) (down-of tile_0_0 tile_0_1) (down-of bottomwall-0 tile_0_0)
    (down-of tile_1_7 upperwall-1) (down-of tile_1_6 tile_1_7) (down-of tile_1_5 tile_1_6) (down-of tile_1_4 tile_1_5) (down-of tile_1_3 tile_1_4) (down-of tile_1_2 tile_1_3) (down-of tile_1_1 tile_1_2) (down-of tile_1_0 tile_1_1) (down-of bottomwall-1 tile_1_0)
    (down-of tile_2_7 upperwall-2) (down-of tile_2_6 tile_2_7) (down-of tile_2_5 tile_2_6) (down-of tile_2_4 tile_2_5) (down-of tile_2_3 tile_2_4) (down-of tile_2_2 tile_2_3) (down-of tile_2_1 tile_2_2) (down-of tile_2_0 tile_2_1) (down-of bottomwall-2 tile_2_0)
    (down-of tile_3_7 upperwall-3) (down-of tile_3_6 tile_3_7) (down-of tile_3_5 tile_3_6) (down-of tile_3_4 tile_3_5) (down-of tile_3_3 tile_3_4) (down-of tile_3_2 tile_3_3) (down-of tile_3_1 tile_3_2) (down-of tile_3_0 tile_3_1) (down-of bottomwall-3 tile_3_0)
    (down-of tile_4_7 upperwall-4) (down-of tile_4_6 tile_4_7) (down-of tile_4_5 tile_4_6) (down-of tile_4_4 tile_4_5) (down-of tile_4_3 tile_4_4) (down-of tile_4_2 tile_4_3) (down-of tile_4_1 tile_4_2) (down-of tile_4_0 tile_4_1) (down-of bottomwall-4 tile_4_0)
    (down-of tile_5_7 upperwall-5) (down-of tile_5_6 tile_5_7) (down-of tile_5_5 tile_5_6) (down-of tile_5_4 tile_5_5) (down-of tile_5_3 tile_5_4) (down-of tile_5_2 tile_5_3) (down-of tile_5_1 tile_5_2) (down-of tile_5_0 tile_5_1) (down-of bottomwall-5 tile_5_0)
    (down-of tile_6_7 upperwall-6) (down-of tile_6_6 tile_6_7) (down-of tile_6_5 tile_6_6) (down-of tile_6_4 tile_6_5) (down-of tile_6_3 tile_6_4) (down-of tile_6_2 tile_6_3) (down-of tile_6_1 tile_6_2) (down-of tile_6_0 tile_6_1) (down-of bottomwall-6 tile_6_0)
    (down-of tile_7_7 upperwall-7) (down-of tile_7_6 tile_7_7) (down-of tile_7_5 tile_7_6) (down-of tile_7_4 tile_7_5) (down-of tile_7_3 tile_7_4) (down-of tile_7_2 tile_7_3) (down-of tile_7_1 tile_7_2) (down-of tile_7_0 tile_7_1) (down-of bottomwall-7 tile_7_0)

    (= (total-cost) 0)
    (= (normal-step-cost) 1)
    (= (slip-step-cost) 2)
  )
  (:utility
    (= (has-reward first-aid-kit-1) 10)
    (= (has-reward first-aid-kit-2) 10)
    (= (has-reward first-aid-kit-3) 10)
    (= (has-reward first-aid-kit-4) 10)
    (= (has-reward diamond-1) 20)
    (= (has-reward diamond-2) 20)
    (= (has-reward diamond-3) 20)
    (= (has-reward diamond-4) 20)
  )
  (:bound 12)
)
