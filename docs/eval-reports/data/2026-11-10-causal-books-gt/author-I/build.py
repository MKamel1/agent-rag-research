import json,re,sys
sys.path.insert(0,'.')
import gt_tools as g
TW,CI='local:14b7e283bdcd','local:f0929288d4f3'
TT='Trustworthy Online Controlled Experiments: A Practical Guide to A/B Testing'
CT='Causal Inference in Python: Applying Causal Inference in the Tech Industry'
# (book, dim, diff, qtype, section, question, excerpt, answer)
R=[]
def a(b,dim,diff,qt,sec,q,ex,ans): R.append((b,dim,diff,qt,sec,q,ex,ans))
# ---- TW
a(TW,'book-passage','easy','Fact-Lookup','Malware Reduction',
 "In Trustworthy Online Controlled Experiments, how many Bing users were in the ad-malware cleanup experiment, and what technical restriction did Microsoft put on page-modifying routines?",
 "Microsoft ran a controlled experiment with 3.8 million users potentially impacted, where basic routines that modify the DOM (Document Object Model) were overridden to allow only limited modifications from trusted sources (Kohavi et al. 2014).",
 "3.8 million users; DOM-modifying routines were overridden so only limited modifications from trusted sources were allowed.")
a(TW,'book-passage','medium','Fact-Lookup','Backend Changes',
 "What revenue lift did Amazon's controlled experiment on the 'people who searched for X bought Y' recommendation algorithm produce, per the Trustworthy Online Controlled Experiments book, despite results that lacked the query words?",
 "One weakness of the algorithm was that some items surfaced that did not contain the words in the search phrase; however, Amazon ran a controlled experiment, and despite this weakness, this change increased Amazon’s overall revenue by 3% – hundreds of millions of dollars.",
 "It increased Amazon's overall revenue by 3%, worth hundreds of millions of dollars.")
a(TW,'table-requirement','medium','Procedure','Designing the Experiment',
 "In the worked example of Trustworthy Online Controlled Experiments, which four questions does the author list to finalize the setup of a test once the hypothesis and practical significance boundary are fixed?",
 "We will use this set of decisions to finalize the design: 1. What is the randomization unit? 2. What population of randomization units do we want to target? 3. How large (size) does our experiment need to be? 4. How long do we run the experiment?",
 "Randomization unit, target population, experiment size, and experiment duration.")
a(TW,'book-passage','hard','Procedure','Peeking at p-values',
 "Trustworthy Online Controlled Experiments warns that repeatedly checking significance while a test is still running biases results; which two fixes does it offer, and which one do Google, LinkedIn and Microsoft use?",
 "Use sequential tests with always valid p-values, as suggested by Johari et al. (2017), or a Bayesian testing framework (Deng, Lu and Chen 2016). 2. Use a predetermined experiment duration, such as a week, for the determining statistical significance. Optimizely implemented a solution based on the first method, whereas the experimentation platforms being used at Google, LinkedIn, and Microsoft use the second.",
 "Sequential tests with always-valid p-values (or Bayesian testing), or a predetermined duration such as a week; Google, LinkedIn and Microsoft use the predetermined duration.")
a(TW,'book-passage','medium','Rationale','Key Assumption: Local Linear Approximation',
 "In the Bing page-speed case study of Trustworthy Online Controlled Experiments, what evidence supports treating the delay-versus-metric curve as a straight line near today's latency, given that they only ever slowed the site down?",
 "Specifically, Bing ran the slowdown experiment with a 100 msec and a 250 msec slowdown. The delta for the 250 msec experiment was \\~2.5 times that of the 100 msec study (within the confidence intervals) for several key metrics, which supports the linearity assumption.",
 "Bing ran 100 msec and 250 msec slowdowns; the 250 msec delta was about 2.5 times the 100 msec delta, consistent with linearity.")
a(TW,'book-passage','hard','Definition','Interrupted Time Series',
 "How does Trustworthy Online Controlled Experiments say an effect is estimated when the same population is observed before and after a change, with no randomized comparison group?",
 "Specifically, it uses multiple measurements over time, before an intervention, to create a model that can provide an estimate for the metric of interest after the intervention – a counterfactual. After the intervention, multiple measurements are taken, and the Treatment effect is estimated as the average difference between the actual values for the metric of interest and those predicted by the model (Charles and Melvin 2004, 130).",
 "Interrupted time series: model the pre-intervention measurements to predict a counterfactual, then average the gap between actual and predicted post-intervention values.")
a(TW,'book-passage','hard','Fact-Lookup','Regression Discontinuity Design',
 "In its discussion of regression discontinuity with a legal age cutoff, what other legal milestone at the same age does Trustworthy Online Controlled Experiments say could contaminate the alcohol-effect study?",
 "For example, a study of the impact of alcohol that chooses the legal age of 21 as the threshold may be contaminated by the fact that this is also the threshold for legal gambling.",
 "Legal gambling, which shares the age-21 threshold with legal drinking.")
a(TW,'book-passage','medium','Fact-Lookup','SIDEBAR: Refuted Observational Causal Studies',
 "In the sidebar on refuted observational studies in Trustworthy Online Controlled Experiments, what happened when Young and Karr compared medical hypotheses from uncontrolled studies against randomized trials?",
 "Of 52 claims in 12 papers, none replicated in the randomized controlled trials. And in 5 of the 52 cases, the direction was statistically significant in the opposite direction of the observational causal study.",
 "None of the 52 claims replicated, and in 5 of them the randomized result was significant in the opposite direction.")
a(TW,'book-passage','medium','Procedure','Ramp Phase One: Pre-MPR',
 "At Bing, how is a new feature typically first exposed in the earliest ramp phase described in Trustworthy Online Controlled Experiments, and what happens after that initial exposure grows?",
 "At Bing, the common ramp-up is single-data center small traffic (e.g., 0.5–2%). When a single data center is ramped up to a decent traffic, then all data centers can ramp up.",
 "Start in a single data center at small traffic (0.5-2%); once it carries decent traffic, ramp up all data centers.")
a(TW,'book-passage','hard','Rationale','Rule-of-Thumb: Ecosystem Value of an Action',
 "Per the social-network example in Trustworthy Online Controlled Experiments, what pattern of results lets you conclude that contamination between variants is probably not a concern for a given experiment?",
 "An experiment with positive impact on the first-order action and no impact on downstream metrics is not likely to have a measurable spillover effect.",
 "A positive effect on the first-order action but no effect on downstream (response) metrics suggests no measurable spillover.")
a(TW,'book-passage','hard','Definition','Reasons the Treatment Effect May Differ between Short-Term and Long-Term',
 "Among the explanations in Trustworthy Online Controlled Experiments for why a change's impact after many months can differ from the first weeks, what is the user-adaptation explanation and which failure example illustrates it?",
 "As users learn and adapt to a change, their behavior changes. For example, product crashes are a terrible user experience that may not turn users away with the first occurrence.",
 "User-learned effects: behavior changes as users adapt; e.g., a single product crash may not drive users away, but frequent crashes eventually do.")
a(TW,'book-passage','medium','Comparison','Method #4: Holdback and Reverse Experiment',
 "How does a reverse experiment differ from a holdback in Trustworthy Online Controlled Experiments, and why is it attractive when network effects or limited supply matter?",
 "In a reverse experiment, we ramp 10% of users back into the Control several weeks (or months) after launching the Treatment to 100% of users. The benefit of this approach is that everyone has received the Treatment for a while.",
 "A holdback keeps 10% in Control after launching to 90%; a reverse experiment launches to 100% then ramps 10% back to Control, so everyone has had the Treatment for a while, letting networks or supply reach equilibrium.")
a(TW,'equation-context','medium','Definition','Type I/II Errors and Power',
 "What power level does Trustworthy Online Controlled Experiments call the industry standard, and what is done before an experiment starts to decide the sample count needed for it?",
 "The industry standard is to achieve at least 80% power in our tests. Therefore, it is common to conduct power analysis before starting the experiment to decide how many samples are needed to achieve sufficient power.",
 "At least 80% power; a power analysis is conducted before the experiment to choose the sample size.")
a(TW,'equation-context','hard','Rationale','Ratio Metrics When Analysis Unit Is Different from Experiment Unit',
 "Why can't the ordinary sample-variance formula be trusted for a click-through-rate metric in Trustworthy Online Controlled Experiments when randomization is by user?",
 "This assumption is satisfied if the analysis unit is the same as the experimental (randomization) unit. It is usually violated otherwise.",
 "The formula assumes i.i.d. samples, which holds only when the analysis unit equals the randomization unit; ratio metrics over pageviews or clicks violate it because of within-user correlation.")
# ---- CI
a(CI,'equation-context','easy','Rationale','The Bias Equation',
 "Using the sales example, how does Causal Inference in Python explain why the raw difference in average amount sold between businesses with and without price cuts is not the causal effect?",
 "As you can see, association is equal to the treatment effect on the treated plus a bias term.",
 "Association equals the ATT plus a bias term reflecting how treated and control differ even without treatment.")
a(CI,'equation-context','medium','Definition','The Most Dangerous Equation',
 "In Causal Inference in Python, after quoting Wainer on dangerous equations and introducing the Brazilian school-score data, which formula does the author present and what do its symbols denote?",
 "The equation he talks about is Moivre’s equation: $$ S E = \\frac { \\sigma } { \\sqrt { n } } $$ where SE is the standard error of the mean, σ is the standard deviation, and n is the sample size.",
 "Moivre's equation, SE = sigma / sqrt(n): standard error of the mean from standard deviation and sample size.")
a(CI,'book-passage','medium','Definition','Immorality or Collider',
 "How does Causal Inference in Python describe what happens to two independent causes of a shared child node when you condition on that child?",
 "In an immorality, the two parent nodes are independent of each other. But they become dependent if you condition on the common effect.",
 "They are independent unconditionally but become dependent once you condition on the common effect (collider).")
a(CI,'book-passage','hard','Rationale','The Hidden Bias in Survival Analysis',
 "In the bank-loan default example of Causal Inference in Python, why does randomizing the credit amount still leave only year-one effects identifiable when defaults are tracked over three years?",
 "Notice how only customers who survived (did not default) in year 1 are observed in year 2 and only customers who survived years 1 and 2 are observed in year 3. This selection makes it so that only the effect of loan size in the first year is identifiable.",
 "Only survivors are observed in later years, so selection on survival breaks the randomization after year one.")
a(CI,'book-passage','hard','Definition','Surrogate Confounding',
 "What does Causal Inference in Python call the proxies you can measure when manager quality itself is unobservable, and do they fully remove the bias?",
 "Those variables are not in the backdoor path, but controlling for them will help reduce the bias (even though it won’t eliminate it). Those variables are sometimes referred to as surrogate confounders.",
 "Surrogate confounders; controlling for them reduces but does not eliminate the bias.")
a(CI,'table-requirement','medium','Fact-Lookup','Noise Inducing Control',
 "In the credit-limit-on-spend regression of Causal Inference in Python, what standard error is reported for the square-root credit limit coefficient once the credit score bucket dummies are added?",
 "| np.sqrt(credit\\_limit) | 14.5953 | 3.523 | 4.142 | 0.000 | 7.673 | 21.518 | You can see that it increases the standard error, widening the confidence interval of the causal parameter.",
 "3.523 (up from 2.988 without the buckets), widening the confidence interval.")
a(CI,'book-passage','medium','Fact-Lookup','Positivity',
 "In Causal Inference in Python's positivity discussion, what happens to inverse propensity weighting when some units have extreme propensity scores even though positivity is not fully broken?",
 "Also, even if positivity is not entirely violated, but some units have very small or large propensity scores, IPW will suffer from high variance.",
 "IPW suffers from high variance.")
a(CI,'book-passage','medium','Comparison','Doubly Robust Estimation',
 "What is the guiding idea of doubly robust estimation in Causal Inference in Python, and which two modeling approaches does it blend?",
 "Doubly robust (DR) estimation is a way of combining both model- and design-based identification, hoping that at least one of them is correct. Here, let’s see how to combine propensity score and linear regression in a way that only one of them needs to be rightly specified.",
 "It combines model-based (outcome regression) and design-based (propensity score) identification so only one must be correctly specified.")
a(CI,'book-passage','hard','Rationale','Why Prediction Is Not the Answer',
 "Why does Causal Inference in Python argue that fitting a standard outcome predictor is a poor way to segment customers for personalized discounts?",
 "This would essentially partition the space on the y-axis, assuming that your predictive model can approximate the target well. However, this wouldn’t necessarily lead to groups with different treatment effects.",
 "Predicting Y splits customers by outcome level, which does not necessarily produce groups with different treatment effects.")
a(CI,'book-passage','easy','Procedure','T-Learner',
 "Why is the first metalearner for categorical treatments in Causal Inference in Python named with a T, and how many outcome models does it need for a binary treatment?",
 "In the binary case, there are only two models that you need to estimate (hence the name T):",
 "The T stands for treatment: one outcome model per treatment, so two models for a binary treatment.")
a(CI,'book-passage','medium','Definition','Staggered Adoption',
 "How does Causal Inference in Python define a cohort when the marketing campaign rolls out to different cities at different dates?",
 "A much more common situation with panel data is the staggered adoption design, where you have multiple groups of units, which I’ll call G, and each group gets treated at a different point in time (or never). Since the timing of the treatment is what defines a group, it’s common to refer to them as a cohort",
 "A cohort is the group of units that gets treated at the same time; the treatment timing defines the group.")
a(CI,'book-passage','hard','Rationale','Online Marketing Dataset',
 "Why does the book's synthetic control chapter in Causal Inference in Python analyze whole cities instead of randomizing which individuals see its online ads?",
 "Since attribution is not the same as incrementality, and since you can’t randomize who gets to see your ads, treating entire geographies and doing some sort of panel data analysis, much like in the previous chapter, is also a good idea for online marketing.",
 "Attribution is not incrementality and ad exposure can't be randomized per person, so treat entire geographies and use panel data methods.")
a(CI,'book-passage','medium','Fact-Lookup','Causal Impact',
 "In Causal Inference in Python, what benefit does the Bayesian formulation give to Google's library that builds counterfactual time series from unaffected series?",
 "by using other time series that are themselves not affected by the treatment. The fact that the method is Bayesian also allows them to give uncertainty metrics quite naturally.",
 "It naturally provides uncertainty metrics for the estimated counterfactual.")
a(CI,'book-passage','hard','Fact-Lookup','Quarter of Birth Instrument',
 "Using birth timing as an instrument, what return to an extra year of schooling on pay did economists estimate in Causal Inference in Python?",
 "By doing that, economists estimated that we should expect one extra year of education to increase wages by 8.5%, on average:",
 "About 8.5% higher wages per additional year of education.")

items=[];con=g.db()
cnt={TW:0,CI:0}
for b,dim,diff,qt,sec,q,ex,ans in R:
    cnt[b]+=1
    n=len(items)+1
    items.append({"question_id":f"Q-CB-I-{n:03d}","tests":"answerable","dimension":dim,"difficulty":diff,"question_type":qt,
      "doc_type":"book","source_paper_id":b,"source_paper_title":TT if b==TW else CT,"section_path":sec,
      "gold_chapter_title":sec,"question_text":q,"passage_excerpt":ex,"answer_text":ans})
def scan(pid,rx):
    r=re.compile(rx,re.I); return sum(1 for (t,) in con.execute("select text from chunks where paper_id=?",(pid,)) if r.search(t))
def absent(b,q,ans,pats,notes,dist):
    ev=[]
    for p in pats:
        e={"pattern":p,"paper_id":b,"hits":scan(b,p)}
        if p in notes:e["note"]=notes[p]
        ev.append(e)
    n=len(items)+1
    items.append({"question_id":f"Q-CB-I-{n:03d}","tests":"absent","dimension":"partial-absent","difficulty":"medium","question_type":"Fact-Lookup",
      "doc_type":"book","question_text":q,"answer_text":ans,"absence_evidence":ev,"nearest_distractor_paper_id":dist})
    return n
# TW absent
tw_ab=absent(TW,"Does Trustworthy Online Controlled Experiments explain how to build a synthetic control from a donor pool of untreated regions to estimate the lift of a geo experiment?",
 "Not in the book: it never covers synthetic controls, donor pools or geo-experiment designs (it treats observational alternatives like interrupted time series, RDD, IV, PSM and difference in differences instead).",
 ["synthetic control","donor (pool|unit)","geo.?experiment"],{}, "local:f0929288d4f3")
ci_ab=absent(CI,"Does Causal Inference in Python show how to correct for sample selection with a Heckman two-step model and the inverse Mills ratio?",
 "Not in the book: it treats selection bias via colliders and conditioning, but never the Heckman correction or inverse Mills ratio.",
 ["heckman","inverse mills|mills ratio","tobit|selection (model|equation)"],{}, "local:14b7e283bdcd")
# CI absent nearest distractor: another causal text
import collections
meta={"author":"Author I","model":"claude-sonnet-5-5","date":"2026-11-10","books":[TW,CI],"counts":None}
out={"_metadata":meta,"ground_truth":items}
c=collections.Counter((i["source_paper_id"] if "source_paper_id" in i else ("TW" if i["question_id"].endswith(f"{tw_ab:03d}") else "CI"),i["dimension"]) for i in items)
meta["counts"]={f"{k[0]}|{k[1]}":v for k,v in c.items()}
json.dump(out,open("author-I/items.json","w"),indent=1,ensure_ascii=False)
print(len(items),[ (i['question_id'],i.get('absence_evidence')) for i in items if i['tests']=='absent'])
