# Fleet Dispatch Optimization: Balancing Member Satisfaction and Cost Efficiency

## AAA Western & Central New York — ERS Dispatch Strategy Research

---

## 1. Problem Statement

AAA WCNY dispatches ~1,000 roadside assistance calls per day across 128 garages (Fleet + Contractor). The current dispatch strategy prioritizes **speed** — the FSL Scheduler sends the closest available driver. This maximizes member satisfaction but does not consider **cost**.

**The question:** Can we accept a small increase in response time (e.g., 5-15 minutes) to dispatch a cheaper resource, without dropping below the 82% member satisfaction target?

**What we want:** A static policy rule — optimal thresholds the scheduler should use — derived from 12 months of historical data and validated against actual member satisfaction surveys.

---

## 2. Mathematical Framework

### 2.1 Decision Variables

For each service call $i$, the dispatcher chooses driver $j$ from a set of eligible candidates $D_i$. Each candidate has measurable attributes:

| Variable | Symbol | Description | Source |
|----------|--------|-------------|--------|
| Distance | $d_{ij}$ | Haversine distance (miles) from driver $j$ to call $i$ location | ServiceResourceHistory GPS |
| Estimated arrival | $t_{ij}$ | Estimated time of arrival = $d_{ij} / v$ where $v$ = average travel speed (25 mph) | Calculated |
| Cost | $c_{ij}$ | Cost to serve = f(distance, driver type, work type) | ERS_Work_Order_Cost__c |
| Skill match | $s_{ij}$ | Binary: does driver $j$ have the required skills for call $i$? | ServiceResourceSkill |
| Driver type | $\tau_j$ | Fleet (salaried) = 0, Contractor = 1 | ERS_Driver_Type__c |

### 2.2 Satisfaction Model

Member satisfaction $S_i$ is a function of actual response time. From survey data analysis:

$$S_i = P(\text{Totally Satisfied} | ATA_i)$$

We model this as a **logistic function** (sigmoid):

$$S_i = \frac{1}{1 + e^{\beta_0 + \beta_1 \cdot ATA_i + \beta_2 \cdot PTA\_Miss_i + \beta_3 \cdot WorkType_i}}$$

Where:
- $ATA_i$ = Actual Time of Arrival (minutes from call creation to on-location)
- $PTA\_Miss_i$ = Binary indicator: did ATA exceed the promised time?
- $WorkType_i$ = Call type encoding (Tow=0, Battery=1, Tire=2, Lockout=3)
- $\beta_0, \beta_1, \beta_2, \beta_3$ = **Coefficients learned from 12 months of survey data**

**Training data:** Every completed SA that received a survey response (ERS_Overall_Satisfaction__c != null). Expected: ~50,000 survey responses over 12 months.

**Output:** For any predicted ATA, the model gives the probability of "Totally Satisfied."

### 2.3 Cost Function

The cost of dispatching driver $j$ to call $i$:

$$C_{ij} = \alpha_0 + \alpha_1 \cdot d_{ij} + \alpha_2 \cdot \tau_j + \alpha_3 \cdot d_{ij} \cdot \tau_j$$

Where:
- $\alpha_0$ = Base dispatch cost (fixed overhead)
- $\alpha_1$ = Cost per mile (fuel, wear)
- $\alpha_2$ = Contractor premium (additional cost for non-fleet drivers)
- $\alpha_3$ = Interaction: contractors may have different per-mile rates
- $d_{ij}$ = Distance from driver to call
- $\tau_j$ = Driver type (0=Fleet, 1=Contractor)

**Coefficients $\alpha$ are estimated from ERS_Work_Order_Cost__c data** — regress actual cost against distance and driver type.

### 2.4 Optimization Objective

**Minimize total cost subject to a satisfaction constraint:**

$$\min_{j \in D_i} \sum_{i=1}^{N} C_{ij}$$

Subject to:

$$\frac{1}{N} \sum_{i=1}^{N} S_i \geq 0.82 \quad \text{(82% satisfaction target)}$$

$$t_{ij} \leq t_{i,best} + \Delta_{max} \quad \text{(max extra wait time)}$$

$$s_{ij} = 1 \quad \text{(skill match required)}$$

Where:
- $t_{i,best}$ = arrival time of the closest eligible driver (the current "best ASAP" option)
- $\Delta_{max}$ = **The policy parameter we're optimizing** — how many extra minutes of wait are acceptable

### 2.5 The Policy Parameter: $\Delta_{max}$

This is the key output. $\Delta_{max}$ is the maximum additional wait time (minutes) we accept to dispatch a cheaper driver.

**The tradeoff curve:**

For each value of $\Delta_{max} \in \{0, 5, 10, 15, 20, 25, 30\}$:
1. Simulate all 12 months of calls
2. For each call, select the cheapest eligible driver within $t_{i,best} + \Delta_{max}$
3. Calculate: predicted satisfaction $\hat{S}$, total cost $\hat{C}$, SLA hit rate
4. Plot: $\Delta_{max}$ vs Satisfaction vs Cost Savings

The **optimal $\Delta_{max}$** is where the marginal cost saving per additional minute of wait starts to diminish AND satisfaction stays above 82%.

---

## 3. Learning Approach

### 3.1 Phase 1: Satisfaction Model (Logistic Regression)

**Goal:** Learn the relationship between ATA and satisfaction.

**Data:**
- Source: Survey_Result__c joined to ServiceAppointment via WorkOrder
- Features: ATA (minutes), PTA miss (binary), WorkType, time of day, day of week
- Label: ERS_Overall_Satisfaction__c = "Totally Satisfied" (binary: 1 or 0)
- Volume: ~50,000 labeled examples over 12 months

**Model:** Logistic regression (interpretable, produces probability, coefficients are explainable to leadership)

$$P(Satisfied) = \sigma(\beta_0 + \beta_1 \cdot ATA + \beta_2 \cdot PTA\_Miss + \beta_3 \cdot WorkType + \beta_4 \cdot Hour + \beta_5 \cdot Weekend)$$

**Output:** Coefficient table showing exactly how each factor impacts satisfaction probability.

Example output:
| Variable | Coefficient | Interpretation |
|----------|-------------|----------------|
| ATA | -0.023 | Each minute of wait reduces satisfaction probability by ~2.3% |
| PTA_Miss | -0.45 | Missing promised time drops satisfaction by ~45% |
| Tow (vs Light) | -0.12 | Tow calls are inherently harder to satisfy |
| Weekend | +0.08 | Weekend callers are slightly more forgiving |

### 3.2 Phase 2: Cost Model (Linear Regression)

**Goal:** Learn the cost-per-call as a function of distance and driver type.

**Data:**
- Source: ERS_Work_Order_Cost__c joined to ServiceAppointment
- Features: Distance (haversine miles), driver type (Fleet/Contractor), work type
- Label: Total cost (Quantity * Unit_Price)
- Volume: All completed SAs with cost data

**Model:** Linear regression

$$Cost = \alpha_0 + \alpha_1 \cdot Distance + \alpha_2 \cdot IsContractor + \alpha_3 \cdot Distance \cdot IsContractor$$

**Output:** Cost function that predicts the cost of sending any driver to any call.

### 3.3 Phase 3: Historical Simulation

**Goal:** For each $\Delta_{max}$ threshold, simulate what would have happened if we had used that policy.

**For each historical SA:**
1. Reconstruct all eligible drivers at dispatch time (from ServiceResourceHistory GPS)
2. Calculate distance from each driver to the call
3. Identify the closest driver (current "ASAP" policy)
4. Identify the cheapest driver within $\Delta_{max}$ extra minutes
5. Calculate: predicted satisfaction (from Phase 1 model) and predicted cost (from Phase 2 model)
6. Record: actual vs simulated outcome

**Output:** A table:

| $\Delta_{max}$ | Avg Satisfaction | Satisfaction Change | Avg Cost | Cost Savings | SLA Hit Rate |
|----------------|-----------------|--------------------|---------|--------------| ------------|
| 0 min (current) | 83% | baseline | $X | baseline | 59% |
| 5 min | 82.5% | -0.5% | $X-Y1 | Y1 saved | 55% |
| 10 min | 81.8% | -1.2% | $X-Y2 | Y2 saved | 48% |
| 15 min | 80.1% | -2.9% | $X-Y3 | Y3 saved | 40% |
| 20 min | 77.5% | -5.5% | $X-Y4 | Y4 saved | 32% |

**The sweet spot:** The $\Delta_{max}$ where cost savings are significant but satisfaction stays ≥ 82%.

### 3.4 Phase 4: Pareto Frontier

Plot a **Pareto frontier** chart:
- X-axis: Total monthly cost
- Y-axis: Satisfaction %
- Each point is a different $\Delta_{max}$ policy
- The curve shows the fundamental tradeoff — you can't improve one without hurting the other
- The "knee" of the curve is the optimal operating point

---

## 4. Data Requirements

### 4.1 Salesforce Queries Needed

| Query | Object | Fields | Volume (est.) |
|-------|--------|--------|---------------|
| Completed SAs | ServiceAppointment | Id, CreatedDate, ActualStartTime, Latitude, Longitude, ERS_PTA__c, ERS_Dispatch_Method__c, WorkType.Name, ServiceTerritoryId | ~300K (12 months) |
| Survey responses | Survey_Result__c | ERS_Overall_Satisfaction__c, ERS_Work_Order__r.Id | ~50K |
| WO → SA link | WorkOrderLineItem | WorkOrderId, Id (→ SA.ParentRecordId) | ~300K |
| Cost data | ERS_Work_Order_Cost__c | Work_Order__c, Quantity, Unit_Price__c | ~300K |
| Driver GPS history | ServiceResourceHistory | ServiceResourceId, Field=LastKnownLatitude/Longitude, NewValue, CreatedDate | ~4.25M |
| Driver skills | ServiceResourceSkill | ServiceResourceId, Skill.MasterLabel | ~500 |
| Territory members | ServiceTerritoryMember | ServiceTerritoryId, ServiceResourceId | ~1K |

### 4.2 Computed Features (per SA)

| Feature | Calculation | Used In |
|---------|-------------|---------|
| ATA | (ActualStartTime - CreatedDate) in minutes; Towbook: use SAHistory "On Location" | Satisfaction model |
| PTA_Miss | Binary: ATA > ERS_PTA__c | Satisfaction model |
| Driver distance | haversine(driver GPS at dispatch time, SA lat/lon) | Cost model, simulation |
| Closest driver distance | min(distance) among eligible drivers | Simulation baseline |
| Cost per call | Sum(Quantity * Unit_Price) from ERS_Work_Order_Cost__c | Cost model |

---

## 5. Implementation Plan — FSL Scheduler Configuration

### 5.1 Current State

The FSL Scheduler uses:
- **Scheduling Policy:** Rules that determine which driver gets assigned
- **Service Objectives:** Priority weights (minimize travel, ASAP, skill match, etc.)
- **Work Rules:** Hard constraints (territory, skills, operating hours)

Currently, the **ASAP** service objective has the highest weight — the scheduler always picks the fastest driver regardless of cost.

### 5.2 Changes to Implement the Optimal Policy

#### A. Service Objectives — Reweight

| Objective | Current Weight | Proposed Weight | Rationale |
|-----------|---------------|----------------|-----------|
| ASAP (minimize wait) | Highest | Reduce by ~20% | Allow non-closest drivers within $\Delta_{max}$ |
| Minimize Travel | Low | Increase | Prefer closer drivers (reduces cost) |
| Skill Match | Required | Required (no change) | Safety — wrong truck = failed service |
| Preferred Resource | Not used | Add with low weight | Prefer Fleet over Contractor when equal |

#### B. Dispatch Policy — Add Cost Awareness

The FSL Scheduler doesn't have a native "cost" objective. To implement cost-aware dispatch:

**Option 1: Extended Match (Configuration only, no code)**
- Set the "Travel Speed Coefficient" in the scheduling policy to account for cost
- Artificially reduce the "speed" of expensive resources so the optimizer deprioritizes them
- Example: Fleet driver at 25mph actual → 25mph in scheduler. Contractor at 25mph actual → 18mph in scheduler (makes them appear further away)

**Option 2: Custom Apex Trigger (Code change in SF)**
- After the scheduler assigns a driver, a trigger checks:
  - Is there a cheaper driver within $\Delta_{max}$ minutes?
  - If yes, reassign to the cheaper driver
- Pros: Precise control, uses our learned $\Delta_{max}$
- Cons: Requires Apex development, adds latency

**Option 3: Dispatcher Decision Support (FSLAPP feature)**
- Don't change the scheduler — let it assign the ASAP driver
- Show dispatchers a "cost optimization suggestion" in the app:
  - "Driver A (assigned) is 5 mi away, ETA 12 min, cost $45"
  - "Driver B (cheaper) is 8 mi away, ETA 18 min, cost $28 — save $17, +6 min wait"
- Dispatcher decides whether to override
- Pros: No SF changes, human in the loop, builds trust before full automation
- Cons: Manual, not scalable to 1000 calls/day

**Recommendation:** Start with **Option 3** (decision support in FSLAPP) to validate the model with real dispatchers. Once proven, move to **Option 1** (scheduler reweighting) for automation.

### 5.3 Code to Build

#### Phase 1: Data Pipeline (Python, runs once)
- `scripts/train_satisfaction_model.py` — Logistic regression on 12 months of survey data
- `scripts/train_cost_model.py` — Linear regression on cost data
- `scripts/simulate_dispatch.py` — Historical simulation for different $\Delta_{max}$ values
- Output: coefficient tables, tradeoff curves, optimal $\Delta_{max}$ recommendation

#### Phase 2: Decision Support UI (FSLAPP feature)
- Extend the SA History Report or Queue Board
- When a call is dispatched, show alternative drivers with cost comparison
- Use the learned cost model to estimate savings
- Track dispatcher acceptance rate

#### Phase 3: Scheduler Integration (SF configuration)
- Adjust Service Objective weights based on the learned optimal $\Delta_{max}$
- Monitor satisfaction and cost weekly to validate

---

## 6. Expected Outcomes

### Conservative Estimate (based on industry benchmarks)

| Metric | Current | With $\Delta_{max}$ = 10 min | Change |
|--------|---------|----------------------------|--------|
| Avg Satisfaction | 83% | 82% | -1% (still above target) |
| Avg ATA | 62 min | 67 min | +5 min |
| Avg cost per call | $X | $X - 12% | -12% savings |
| Monthly cost savings | — | ~$15K-25K (est.) | Significant |
| SLA (45 min) hit rate | 59% | 52% | -7% (tradeoff) |

### What the Model Will Tell You

1. **The exact $\Delta_{max}$** where satisfaction hits 82% — the maximum you can stretch
2. **Which territories benefit most** from cost optimization (high contractor usage)
3. **Which work types are most sensitive** — tow calls may have zero tolerance, battery calls may accept 15 min
4. **Time-of-day patterns** — evening calls may accept more delay than rush hour
5. **The Pareto frontier** — the complete tradeoff curve for leadership to make an informed decision

---

## 7. Risks and Limitations

| Risk | Mitigation |
|------|-----------|
| Survey data is sparse (~20% response rate) | Use ATA/PTA as secondary signal for validation |
| GPS data gaps (28% coverage for Fleet) | Exclude calls with no GPS from simulation; report coverage % |
| Cost data may not exist for all calls | Use distance as proxy where cost is missing |
| Model may not generalize to future conditions | Retrain quarterly; monitor satisfaction weekly |
| Dispatcher resistance to "slower" dispatch | Start with suggestions (Option 3), not automation |
| Seasonal effects (winter = more calls, longer ATA) | Include month/season as feature in satisfaction model |

---

## 8. Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. Data extraction & cleaning | 1 week | Clean dataset of 300K SAs with cost, satisfaction, GPS |
| 2. Model training | 1 week | Satisfaction coefficients, cost function, tradeoff curves |
| 3. Historical simulation | 1 week | Optimal $\Delta_{max}$, Pareto frontier, per-territory analysis |
| 4. Decision support UI | 2 weeks | Cost comparison feature in FSLAPP |
| 5. Scheduler reweighting | 1 week | Updated Service Objectives in SF (after validation) |
| **Total** | **6 weeks** | Full optimization from analysis to production |
