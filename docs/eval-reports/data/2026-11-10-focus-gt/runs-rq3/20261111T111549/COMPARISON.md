| arm | contam@10 focus | off@rank1 focus | contam@10 papers | collision hit/26 | papers-on hit/38 | papers-off hit/17 | books hit/74 | legit recall/14 | dist>gold | lookalike>gold | errors | results/q | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 0.100 | 0 | 0.118 | 21 | 30 | 16 | 54 | 14 | 0 | 0 | 0 | 10.00 | (comparator) |
| penalty-0.30-p5 | 0.112 | 0 | 0.126 | 21 | 30 | 16 | 54 | 14 | 0 | 0 | 0 | 10.00 | REJECT |
| tail-0.25 | 0.112 | 0 | 0.116 | 20 | 30 | 12 | 54 | 8 | 0 | 0 | 0 | 10.00 | REJECT |
| tail-0.30 | 0.154 | 1 | 0.142 | 19 | 29 | 8 | 54 | 8 | 0 | 0 | 0 | 10.00 | REJECT |

- penalty-0.30-p5: fails focus contamination@10 <= 0.5 x baseline; papers-set contamination@10 does not rise
- tail-0.25: fails focus contamination@10 <= 0.5 x baseline; offtopic-legit paper recall drop <= 1; papers off-topic member hit drop <= 1
- tail-0.30: fails focus contamination@10 <= 0.5 x baseline; papers-set contamination@10 does not rise; collision member hit drop <= 1; offtopic-legit paper recall drop <= 1; papers off-topic member hit drop <= 1
