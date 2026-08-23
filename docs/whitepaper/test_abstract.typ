
#set page(paper: "a4")
#let brand-navy = rgb("#0A2540")
#let brand-blue = rgb("#0073E6")
#let text-dark = rgb("#1A202C")
#let border-color = rgb("#CBD5E1")

#align(center + horizon)[
  #text(size: 24pt, weight: "bold", fill: brand-navy)[PredSea White Paper]

  #align(left)[
    #rect(
      width: 100%,
      fill: rgb("#F0F7FF"),
      stroke: (left: 4pt + brand-blue, rest: 0.5pt + border-color),
      radius: (right: 6pt),
      inset: 14pt
    )[
      #text(weight: "bold", size: 11pt, fill: brand-navy)[Abstract]
      #v(0.6em)
      #text(size: 9.5pt, fill: text-dark)[
        PredSea introduces a serverless, cloud-native oceanographic forecasting architecture at an operational cost of ~\.22 per daily forecast cycle.
      ]
    ]
  ]
]
