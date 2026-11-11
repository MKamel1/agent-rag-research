I=[]
def a(p,dim,diff,qt,q,ex,ans): I.append(dict(p=p,dim=dim,diff=diff,qt=qt,q=q,ex=ex,ans=ans))
a("2306.01969","method-detail","medium","Method","In the individual-level interactive fixed effects estimator that uses several related outcomes, how is the number of pretreatment outcomes used as regressors chosen?",
"To select the number of pretreatment outcomes to include in the model, we follow a model selection procedure similar to that in Hsiao et al. (2012), where for each usable number of pretreatment outcomes, we construct many diferent models by including a random subset of the pretreatment outcomes as regressors and the remaining outcomes as instruments. We then estimate the models using GMM and obtain the leave-one-out prediction errors for all or a subsample of the individuals.",
"Build many models with random subsets of pretreatment outcomes as regressors and the rest as instruments, estimate by GMM, and choose the number minimising mean squared leave-one-out prediction error.")
a("2606.22126","paper-passage","hard","Result-Comprehension","In the ablation of how multidimensional information is fused in the TSAlign time-series-language model, why does uniform fusion perform worst and what does the gated variant do better than softmax weighting?",
"Uniform fusion yields the lowest accuracy, as it treats all dimensions equally. Scalar-weight fusion provides moderate gains but remains limited in expressiveness. Softmax-based fusion further improves performance with adaptive weighting, yet its competitive normalization suppresses useful signals.",
"Uniform fusion treats all dimensions equally so it is worst; softmax's competitive normalization suppresses useful signals, whereas gated fusion lets multiple informative dimensions be preserved and combined.")
a("2212.13145","paper-passage","medium","Limitation","What drawback do the authors identify for orthogonal-signal estimation of ratios of conditional expectations when propensity scores are near zero, and why is it worse with data combination?",
"Inverse probability weighting (IPW) is known to suffer from unstable estimates especially when the propensity score is close to zero",
"IPW-type orthogonal signals are unstable when propensity scores are near zero; worse in data combination (two-sample LATE/IDID) where four- or eight-class classification is needed.")
a("2210.11186","equation-context","medium","Result-Comprehension","When a detector is coupled linearly to the stress-energy tensor of a scalar field in Friedmann spacetimes instead of to the field itself, what does the first-order transition probability turn out to depend on?",
"Thus, we find that the transition probability (and hence, the response rate) depends on the correlations of the stress energy tensors between the points lying on the trajectory of the detector.",
"It depends on correlations of the stress-energy tensor operators between points on the detector's trajectory.")
a("2606.15637","method-detail","easy","Fact-Lookup","In the synthetic experiments for the cardiac electrophysiology digital twin with context-conditioned identifiable latent diffusion, how many samples were generated and how were they split?",
"This resulted in ∼ 2, 376 samples which we split into train/val/test sets with a 60:20:20 ratio.",
"About 2,376 samples, split 60:20:20 into train/val/test.")
a("2512.19349","paper-passage","easy","Fact-Lookup","In the LLM-generated-confounder and CEVAE feedback-loop framework, how large is the Twins dataset used for evaluation?",
"• Sample Size: 20,000 individuals (10,000 twin pairs).",
"20,000 individuals, i.e. 10,000 twin pairs.")
a("2605.00374","equation-context","hard","Method","For edge classification with high-dimensional edge features treated as the causal treatment, how is the representation-balancing loss modified relative to one-dimensional treatments?",
"Consequently, we adjust the loss function to use the 2-norm to measure the difference between the estimated and observed edge features <sup>3</sup>:",
"The loss uses the squared 2-norm of the difference between estimated and observed edge feature vectors.")
a("2512.18997","numeric-result","easy","Result-Comprehension","In the COVID-19 social-distancing application of the factorial matched design, what was the post-matching absolute standardized mean difference for non-work trip reductions when comparing (h, h) with (l, h)?",
"For example, as shown in Table 4, in the comparison between (h, h) $( h , h )$ and (l, h) after matching, the absolute standardized mean diference for the percentage reduction in non-work trips (i.e., the contrast of the second treatment component: (·, h) vs. (·, h)) is 0.05, indicating that this treatment dose is not meaningfully diferent between these two groups.",
"0.05, indicating good balance on that treatment component.")
a("2103.15218","paper-passage","medium","Result-Comprehension","In the simulation comparing propensity-score estimators for combining a probability sample with a non-probability sample, how did the plain IPW estimators fare on bias, coverage and standard errors?",
"In all three, the IPW estimators performed the worst overall in terms of % bias. Similar to Chen, Li & Wu (2019), the coverage rates of IPW were suboptimal in all scenarios and the standard error was substantially underestimated.",
"IPW had the highest bias, suboptimal coverage, and substantially underestimated standard errors.")
a("2202.02369","numeric-result","medium","Result-Comprehension","In the immortal-time-bias simulation under Scenario 5, what were the estimated biases for the including-IMT, excluding-IMT and prescribed-time-distribution-matching approaches?",
"Under this scenario, the biases for including IMT, excluding IMT, and PTDM are -1.409, -0.933, and -0.417, respectively.",
"-1.409 (including IMT), -0.933 (excluding IMT), -0.417 (PTDM).")
a("2402.06032","equation-context","hard","Rationale","In the causal network contagion VaR procedure, why are the marginals estimated with a shifted empirical distribution function before being mapped to normal scores?",
"We use the adjusted empirical distributions, in order to avoid degenerate values for z.",
"The adjusted empirical CDF (0.5 offset, N+1 denominator) keeps values away from 0 and 1 so the normal-score transform does not give degenerate (infinite) values.")
a("1803.08218","paper-passage","easy","Fact-Lookup","In the survival-analysis causal study of breast cancer patients treated at centres in India, how many patients were in the dataset and how many covariates did each have?",
"The dataset used for this analysis was collected from multiple cancer treatment centers across different cities in India, and was focused on breast cancer patients (1806 total).",
"1806 breast cancer patients (with 110 covariates per patient).")
a("2607.06664","numeric-result","medium","Result-Comprehension","In the 3D core-collapse models of a 9 solar-mass progenitor with different initial spins, what was the end-of-simulation alignment (dot product) between angular momentum and kick direction for the three slowest-rotating models?",
"For models 9-rot-0.0, 9-rot-0.01, and 9-rot-0.1 respectively, the dot product of the angular momentum and kick unit vectors at the end of the simulations is ∼0.8, 0.76, and ∼0.0, and it varies significantly with time during their evolution.",
"About 0.8, 0.76 and about 0.0 respectively.")
a("2210.15829","method-detail","medium","Method","In the D-RSMD estimator for heterogeneous treatment effects with conditional moments, how are the nuisance parameters estimated and how flexible is the polynomial basis?",
"All of the nuisance parameters for the D-RSMD estimator in the simulation and empirical application are estimated by the Lasso method with cross validation. The maximum degree of the polynomial for the nuisance parameters is 5,",
"Lasso with cross-validation, with polynomials up to degree 5 in all controls.")
a("2604.02293","method-detail","easy","Method","In the simulation for the covariate-balanced stacked difference-in-differences estimator, what is the true dynamic treatment effect path by event time?",
"The treatment efect path is set to zero for all pretreatment event times, equal to −0.40 at treatment onset, equal to −0.80 one period after adoption, and equal to −1.10 for all subsequent post-treatment periods in the simulation window.",
"Zero before treatment, -0.40 at onset, -0.80 one period later, -1.10 afterwards.")
a("1808.04246","equation-context","hard","Method","In the semiparametric Bayesian treatment-effect work with a Dirichlet process prior on the covariate distribution, what happens to the posterior formula when the Dirichlet process precision measure is set to zero?",
"This formula remains valid if $\\nu = 0$ , which yields the Bayesian bootstrap, see Chapter 4.7 of [18], and is also covered in the theorems below.",
"The formula stays valid and yields the Bayesian bootstrap.")
a("2602.07825","paper-passage","medium","Result-Comprehension","In the simulation study of estimators for causal decomposition with allowability specifications, which estimator strategies performed best in terms of bias and coverage?",
"The N-bridging estimators dominated all other strategies in their respective classes, achieving the lowest bias and most accurate coverage. The Z-Bridge-SWR and N-Bridge-SWR estimators had the best performance across all estimators.",
"N-bridging estimators dominated within their classes; Z-Bridge-SWR and N-Bridge-SWR were best overall.")
a("2510.16975","method-detail","medium","Method","How were the true variance-component values and the replicate datasets generated in the simulation for the causal variance decomposition of hospital-based health inequality?",
"To compute the true variance component values, we generated a super-population of 10,000 observations for each simulation scenario, using the known parameter values and applied the decomposition to this super-population to obtain Monte Carlo approximations that serve as benchmarks for evaluating estimator performance. For estimator evaluation, we generated 1,000 samples under each scenario from the same data-generating mechanism.",
"A super-population of 10,000 observations per scenario gave Monte Carlo true values; 1,000 samples per scenario were used for evaluating estimators.")
a("1406.0531","method-detail","medium","Method","In the synthetic studies of the witness-based instrumental variable bounds method, how are the conditional probabilities of each vertex given its parents generated?",
"The conditional probabilities of a vertex given its parents are generated by a logistic regression model with pairwise interactions, where parameters are sampled according to a zero mean Gaussian with standard deviation 20 / number of parents.",
"A logistic regression with pairwise interactions, parameters drawn from a zero-mean Gaussian with standard deviation 20 divided by number of parents.")
a("2105.00416","paper-passage","hard","Rationale","In the Lalonde job-training data analysis with Lasso-based variable selection, why are the naive confidence intervals shorter than the selective-inference ones?",
"As shown in Table 4, for all variables, the confidence interval for Naive is shorter than that for SI. This is because, as mentioned in the previous section, Naive ignores that the selected variable is likely to be significant.",
"Naive intervals ignore that a selected variable is likely to be significant (selection effect), so they are too short.")
a("2410.23521","numeric-result","medium","Result-Comprehension","In the simulation of antihypertensive treatment in pregnancy, in scenario 2 what bias did the Kaplan-Meier estimator show for the risk difference and log risk ratio of small-for-gestational-age live birth, versus the Aalen-Johansen estimator that censored healthy live births?",
"Considering again scenario 2, the bias in the RD and (log-transformed) RR estimates from the KM estimator were -0.04 and 0.14. The corresponding bias estimates for the AJ estimator that censored non-SGA live birth were -0.07 and 0.06.",
"KM: -0.04 (RD) and 0.14 (log RR); AJ censoring non-SGA live births: -0.07 and 0.06.")
a("2606.23548","numeric-result","easy","Result-Comprehension","In the benchmark of the graph-network surrogate for superconducting tape-stack circuits against ngspice, what peak speedup did GPU inference reach on larger circuits?",
"However, as seen in panel (b),GPU inference is competitive with or faster than ngspice across the majority of configurations, achieving a peak ngspice/GPU speedup of 2.5× for larger circuits.",
"A peak speedup of 2.5x over ngspice for larger circuits.")
a("1509.03940","method-detail","medium","Rationale","In the eBay product-release hierarchical Bayesian time-series model, which autoregressive order was adopted and why?",
"However, the AR(4) model performs better than the AR(0) and AR(1) models (with minimal computational overhead), so we proceed with the $\\mathrm { A R } ( 4 )$ model in all subsequent analyses.",
"AR(4), because it fit better than AR(0) and AR(1) with minimal extra computation, while the causal effect estimate was insensitive to the order.")
a("2510.14780","method-detail","easy","Fact-Lookup","In the simulations for causal discovery with dependent latent variables using higher-order cumulants, what distribution do the disturbances follow?",
"All disturbances are assumed to follow a log-normal distribution, $u _ { i } \\sim$ Lognormal(−1.1, 0.8), shifted to have zero mean by subtracting its expected value.",
"Log-normal(-1.1, 0.8), shifted to zero mean.")
a("2606.05448","equation-context","easy","Fact-Lookup","In the Bayesian parameter identification for the FluidFlower CO2 injection experiment, what thresholds convert the surrogate's continuous predictions of dissolved concentration and gas saturation into binary plume maps?",
"where $C _ { \\mathrm { t h r } } \\ = \\ 0 . 2 1$ and $S _ { \\mathrm { t h r } } ~ = ~ 0 . 0 0 1$ are the reference thresholds used to identify dissolved and gaseous plume regions, respectively [22].",
"Concentration threshold 0.21 and saturation threshold 0.001.")
a("2605.23691","numeric-result","medium","Result-Comprehension","In the simulations for the joint marginal and heterogeneous treatment effect model, what power did the adjusted model reach when the outcome is continuous and covariates have no predictive effect, versus the unadjusted model at tau = 0.5?",
"Under MI, the power to detect a treatment efect of $\\tau = 0 . 5$ is approximately 60% across all scenarios, as intended by the design. Under NAMI-HTE, power increases substantially due to adjustment. For the continuous outcome without predictive efects, power increases to approximately 83%.",
"About 83% for the adjusted model versus about 60% for the unadjusted one.")
a("2107.03922","numeric-result","medium","Result-Comprehension","In the re-analysis of the propensity-score weighting simulation, how much did adding second-order moment balancing reduce absolute bias for CBPS and for entropy balancing?",
"In the case of CBPS, the absolute bias across simulations for a scenario with non-linear and non-additive terms is reduced from 0.48 to around 0.16. For EB, the absolute bias is reduced from 0.36 to 0.09 .",
"CBPS from 0.48 to about 0.16; EB from 0.36 to 0.09.")
a("2606.21613","numeric-result","easy","Result-Comprehension","In the wildlife monitoring system that corroborates camera-trap and audio evidence, what precision, recall and F1 did the acoustic deer-call classifier achieve on its validation set?",
"The acoustic classifier achieves a positive-class precision of 0.963, recall of 0.985, and F1 of 0.974 on the validation set, correctly identifying 129 of 131 deer vocalizations while producing only 5 false positives across 988 background clips.",
"Precision 0.963, recall 0.985, F1 0.974 (129 of 131 calls found, 5 false positives in 988 background clips).")
a("2207.13512","method-detail","medium","Rationale","For selecting among non-stationary GEV models of temperature extremes, which information criterion is used and why?",
"To choose the best model out of the diferent models presented here, we apply the Bayesian Information Criterion (BIC; [66]). In a simulation study by [35], the BIC performed better than the",
"BIC, because a prior simulation study found it performed better than AIC for non-stationary GEV distributions.")
a("2504.00785","method-detail","hard","Rationale","Why does the quantile treatment effect method for high-dimensional panels with factor models use a block bootstrap for inference rather than a pairwise bootstrap?",
"Compared to the conventional pairwise bootstrap, the blockwise bootstrap respects the sequential order of the data by putting a certain number of sequential observations into one block, and taking random draws among the blocks.",
"The common factors may be time dependent; blocks of sequential observations preserve time-series ordering.")
