# Import itertools

import itertools

# Participant picks

picks_dict = {
'amir':     ['W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',    'L',	'W',	'W',	'L',	'W',	'L',	'L',	'W'],
'andy':     ['W',	'L',	'W',	'L',	'W',	'W',	'L',	'W',	'L',	'W',	'W',	'W',	'W',	'W',	'L',	'L',	'W'],
'buhduh':   ['W',	'W',	'L',	'L',	'W',	'W',	'W',	'L',	'W',	'W',	'L',	'W',	'W',	'W',	'W',	'L',	'L'],
'emer':     ['W',	'L',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'L',    'W',	'W',	'L',	'W',	'L',	'W'],
'hanan':    ['W',	'L',	'W',	'L',	'W',	'W',	'W',	'W',	'W',    'L',	'W',	'W',	'W',	'W',	'L',	'W',	'W'],
'jacob':    ['W',	'W',	'L',	'W',	'W',	'W',	'L',	'W',	'L',	'W',	'W',	'W',	'W',	'W',	'L',	'W',	'W'],
'jay':      ['W',   'W',    'W',    'W',	'W',	'W',	'W',	'W',	'W',	'L',	'W',	'W',	'W',	'W',	'L',	'W',	'W'],
'jen':      ['W',	'L',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'L',	'W',	'W',	'L',	'W',	'W',	'L',	'W'],
'marsha':   ['W',	'L',	'W',	'W',	'W',	'L',	'W',	'W',	'L',	'W',	'L',	'W',	'W',	'W',	'W',	'L',	'W'],
'nathan':   ['W',	'L',	'W',	'W',	'W',	'W',    'W',	'W',	'W',	'L',	'L',	'W',    'L',	'W',	'L',	'L',	'W'],
'pop':      ['W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W',	'W'],
'sarah':    ['W',	'W',	'W',	'W',	'W',	'W',	'L',	'W',	'L',	'L',	'W',	'W',	'W',	'W',	'L',	'W',	'W']
}

# Pre-calculate predicted final record for tiebreaker
predicted_wins = {name: picks.count('W') for name, picks in picks_dict.items()}

# Indices (0-based) of intra-division games vs. Cowboys, Commanders, Giants (6 total); adjust as needed
division_weeks = [0, 5, 7, 10, 14, 16]

# Pre-calculate predicted division record for second tiebreaker
predicted_division_wins = {
    name: sum(1 for i in division_weeks if picks[i] == 'W')
    for name, picks in picks_dict.items()
}

# Pre-calculate predicted total points guess for final tiebreaker
predicted_points = {
    'amir': 470,
    'andy':   418,
    'buhduh': 357,
    'emer': 455,
    'hanan': 450,
    'jacob': 422,
    'jay': 486,
    'jen': 455,
    'marsha': 476,
    'nathan': 433,
    'pop': 340,
    'sarah': 432,
}

# Actual total points scored by the Eagles at season end
actual_points = (24+20+33+31+17+17+28+38+10+16+21+15+19+31+29+13+17) / 17 * 17 # ⭐️⭐️⭐️⭐️⭐️⭐️⭐️

# Eagles in-season performance (W for win; L for loss; A for not played yet)

eagles_results = [
    'W', # 1 Cowboys
    'W', # 2 Chiefs
    'W', # 3 Rams
    'W', # 4 Bucs
    'L', # 5 Broncos
    'L', # 6 Giants
    'W', # 7 Vikings
    'W', # 8 Giants
    'W', # 10 Packers
    'W', # 11 Lions
    'L', # 12 Cowboys
    'L', # 13 Bears
    'L', # 14 Chargers
    'W', # 15 Raiders
    'W', # 16 Comms
    'W', # 17 Bills
    'L'  # 18 Comms
] # ⭐️⭐️⭐️⭐️⭐️⭐️⭐️

# Number of games in this season (auto-adjusts for mini-season testing)
total_weeks = len(eagles_results)

# Create points tally

tally_total = {'amir':0, 'andy':0, 'buhduh':0, 'emer':0, 'hanan':0, 'jacob':0, 'jay':0, 'jen':0, 'marsha':0, 'nathan':0, 'pop':0, 'sarah':0}

weight = {
    0:  .687, # 1 Cowboys
    1:  .474, # 2 Chiefs
    2:  .584, # 3 Rams
    3:  .544, # 4 Bucs
    4:  .626, # 5 Broncos
    5:  .744, # 6 Giants
    6:  .525, # 7 Vikings
    7:  .628, # 8 Giants
    8:  .441, # 10 Packers
    9:  .508, # 11 Lions
    10: .566, # 12 Cowboys
    11: .687, # 13 Bears
    12: .587, # 14 Chargers
    13: .782, # 15 Raiders
    14: .621, # 16 Comms
    15: .494, # 17 Bills
    16: .736  # 18 Comms
    } # ⭐️⭐️⭐️⭐️⭐️⭐️⭐️

# Tally competitors' points

current_points = {'amir':0, 'andy':0, 'buhduh':0, 'emer':0, 'hanan':0, 'jacob':0, 'jay':0, 'jen':0, 'marsha':0, 'nathan':0, 'pop':0, 'sarah':0}

for name,picks in picks_dict.items():
    for week in range(total_weeks):
        if picks[week] == eagles_results[week]:
            current_points[name] += 1

# Calculate current week

week_number = 0
for week in range(total_weeks):
    if eagles_results[week] != 'A':
        week_number += 1

week_range = total_weeks - week_number

# Probabilistic "closest to points" helper using a Normal model
def closest_shares_normal(guesses_dict, mean, sd):
    # guesses_dict: {name: guess_points}
    # returns shares summing to 1.0 based on probability each guess is closest
    import math
    if sd <= 0:
        sd = 1.0
    def cdf(x):
        return 0.5 * (1.0 + math.erf((x - mean) / (sd * (2 ** 0.5))))

    names_sorted = sorted(guesses_dict.keys(), key=lambda n: guesses_dict[n])
    shares = {n: 0.0 for n in names_sorted}
    for i, name in enumerate(names_sorted):
        g = guesses_dict[name]
        left = -float('inf') if i == 0 else (guesses_dict[names_sorted[i-1]] + g) / 2.0
        right = float('inf') if i == len(names_sorted) - 1 else (g + guesses_dict[names_sorted[i+1]]) / 2.0
        shares[name] = max(0.0, cdf(right) - cdf(left))
    total = sum(shares.values())
    if total > 0:
        for k in shares:
            shares[k] /= total
    return shares

# Create list of all possible outcomes

l = ['W', 'L']
outcomes = [list(i) for i in itertools.product(l, repeat = week_range)]
print('')
print('Remaining outcomes:', len(outcomes))
print('')
print('----------')


# WEIGHTED -------------------------------------------------------------------------------------------

week_number_wins = sum(1 for result in eagles_results[:week_number] if result == 'W')

# Define function
def outcome_chance_weighted(outcome):
    chance = 1
    for i in range(week_number, total_weeks):
        if outcome[i - week_number] == 'W':
            chance = chance * weight[i]
        else:
            chance = chance * (1 - weight[i])
    return chance

# Iterate through each one

for outcome in outcomes:
    tally_dict = {}
    chance = outcome_chance_weighted(outcome)
    for name,predictions in picks_dict.items():
        tally_dict[name] = current_points[name] 
        for week in range(week_number, total_weeks):
            if predictions[week] == outcome[week - week_number]:
                tally_dict[name] += 1
    max_value = max(tally_dict.values())
    tied_names = [name for name, matches in tally_dict.items() if matches == max_value]
    if len(tied_names) == 1:
        tally_total[tied_names[0]] += chance * 100
    elif len(tied_names) > 1:
        actual_wins = outcome.count('W') + week_number_wins
        closest_diff = min(abs(predicted_wins[name] - actual_wins) for name in tied_names)
        winners = [name for name in tied_names if abs(predicted_wins[name] - actual_wins) == closest_diff]
        # SECOND TIEBREAKER: division record closeness
        if len(winners) > 1:
            # Calculate actual division wins for this simulated outcome
            actual_division_wins = sum(
                (eagles_results[i] == 'W') if i < week_number else (outcome[i-week_number] == 'W')
                for i in division_weeks
            )
            closest_div_diff = min(
                abs(predicted_division_wins[name] - actual_division_wins)
                for name in winners
            )
            winners = [
                name for name in winners
                if abs(predicted_division_wins[name] - actual_division_wins) == closest_div_diff
            ]
        # FINAL TIEBREAKER (Probabilistic): total points "closest" as a distribution
        # Allocate winner shares based on probability each guess ends up closest
        weeks_remaining = total_weeks - week_number
        sd_per_game = 11.0  # tunable
        sd_remaining = max(1.0, sd_per_game * (weeks_remaining ** 0.5))
        mean_points = actual_points  # current rolling estimate

        guesses_subset = {w: predicted_points[w] for w in winners}
        shares = closest_shares_normal(guesses_subset, mean_points, sd_remaining)

        for w in winners:
            tally_total[w] += chance * 100 * shares[w]

print('')
print('Weighted:')
print('')

for person,percent in tally_total.items(): # Percent
    print(person, ':', round(percent,1), '%')

print('')
print('Correct picks (so far):')
print('')
for person, pts in current_points.items():
    print(person, ':', pts)

print('')
print('W COPY: ')
print('')

copy_weighted = []
for percent in tally_total.values():
    copy_weighted.append(round(percent,1))

print(copy_weighted)

print('')
print('----------')



# STRAIGHT -------------------------------------------------------------------------------------------------

# Iterate through each one

tally_total = {'amir':0, 'andy':0, 'buhduh':0, 'emer':0, 'hanan':0, 'jacob':0, 'jay':0, 'jen':0, 'marsha':0, 'nathan':0, 'pop':0, 'sarah':0}

for outcome in outcomes:
    tally_dict = {}
    for name,predictions in picks_dict.items():
        tally_dict[name] = current_points[name]
        for week in range(week_number, total_weeks):
            if predictions[week] == outcome[week - week_number]:
                tally_dict[name] += 1
    max_value = max(tally_dict.values())
    tied_names = [name for name, matches in tally_dict.items() if matches == max_value]
    if len(tied_names) == 1:
        tally_total[tied_names[0]] += 1
    elif len(tied_names) > 1:
        actual_wins = outcome.count('W') + week_number_wins
        closest_diff = min(abs(predicted_wins[name] - actual_wins) for name in tied_names)
        winners = [name for name in tied_names if abs(predicted_wins[name] - actual_wins) == closest_diff]
        # SECOND TIEBREAKER: division record closeness
        if len(winners) > 1:
            # Calculate actual division wins for this simulated outcome
            actual_division_wins = sum(
                (eagles_results[i] == 'W') if i < week_number else (outcome[i-week_number] == 'W')
                for i in division_weeks
            )
            closest_div_diff = min(
                abs(predicted_division_wins[name] - actual_division_wins)
                for name in winners
            )
            winners = [
                name for name in winners
                if abs(predicted_division_wins[name] - actual_division_wins) == closest_div_diff
            ]
        # FINAL TIEBREAKER (Probabilistic): total points "closest" as a distribution
        weeks_remaining = total_weeks - week_number
        sd_per_game = 11.0  # tunable
        sd_remaining = max(1.0, sd_per_game * (weeks_remaining ** 0.5))
        mean_points = actual_points

        guesses_subset = {w: predicted_points[w] for w in winners}
        shares = closest_shares_normal(guesses_subset, mean_points, sd_remaining)

        for w in winners:
            tally_total[w] += shares[w]

# print('')
# print('Straight:')
# print('')

# number_outcomes = len(outcomes) # Percent
# percentages = {person:(outcome/number_outcomes)*100 for person,outcome in tally_total.items()}

# for person,percent in percentages.items():
#     print(person, ':', round(percent,1), '%')

# print('')
# print('S COPY: ')
# print('')

# copy_straight = []
# for percent in percentages.values():
#     copy_straight.append(round(percent,1))

# print(copy_straight)

# print('')
# print('----------')
# print('')


# --- BEGIN: Simulation API function ---
def run_simulation(eagles_results_input, weight_input, picks_dict_input, division_weeks_input, predicted_points_input, actual_points_input):
    import itertools

    # Use passed-in results and weights
    
    eagles_results = eagles_results_input
    weight = weight_input
    picks_dict = picks_dict_input
    division_weeks = division_weeks_input
    predicted_points = predicted_points_input
    actual_points = actual_points_input

    predicted_wins = {name: picks.count('W') for name, picks in picks_dict.items()}
    predicted_division_wins = {
        name: sum(1 for i in division_weeks if picks[i] == 'W')
        for name, picks in picks_dict.items()
    }

    total_weeks = len(eagles_results)
    current_points = {name: 0 for name in picks_dict}
    for name, picks in picks_dict.items():
        for week in range(total_weeks):
            if picks[week] == eagles_results[week]:
                current_points[name] += 1

    week_number = sum(1 for r in eagles_results if r != 'A')
    week_range = total_weeks - week_number
    outcomes = [list(i) for i in itertools.product(['W','L'], repeat=week_range)]
    week_number_wins = sum(1 for result in eagles_results[:week_number] if result == 'W')

    def outcome_chance_weighted(outcome):
        chance = 1
        for i in range(week_number, total_weeks):
            if outcome[i - week_number] == 'W':
                chance *= weight[i]
            else:
                chance *= (1 - weight[i])
        return chance

    # Probabilistic "closest to points" helper using a Normal model
    def closest_shares_normal(guesses_dict, mean, sd):
        import math
        if sd <= 0:
            sd = 1.0
        def cdf(x):
            return 0.5 * (1.0 + math.erf((x - mean) / (sd * (2 ** 0.5))))
        names_sorted = sorted(guesses_dict.keys(), key=lambda n: guesses_dict[n])
        shares = {n: 0.0 for n in names_sorted}
        for i, name in enumerate(names_sorted):
            g = guesses_dict[name]
            left = -float('inf') if i == 0 else (guesses_dict[names_sorted[i-1]] + g) / 2.0
            right = float('inf') if i == len(names_sorted) - 1 else (g + guesses_dict[names_sorted[i+1]]) / 2.0
            shares[name] = max(0.0, cdf(right) - cdf(left))
        total = sum(shares.values())
        if total > 0:
            for k in shares:
                shares[k] /= total
        return shares

    weighted_tally = {name: 0 for name in picks_dict}
    straight_tally = {name: 0 for name in picks_dict}

    for outcome in outcomes:
        chance = outcome_chance_weighted(outcome)
        # simulate weighted and straight for each outcome
        def simulate(is_weighted):
            tally = {name: current_points[name] for name in picks_dict}
            for name, predictions in picks_dict.items():
                for week in range(week_number, total_weeks):
                    if predictions[week] == outcome[week - week_number]:
                        tally[name] += 1
            max_score = max(tally.values())
            tied = [name for name, score in tally.items() if score == max_score]
            if len(tied) == 1:
                if is_weighted:
                    weighted_tally[tied[0]] += chance * 100
                else:
                    straight_tally[tied[0]] += 1
            else:
                actual_wins = outcome.count('W') + week_number_wins
                # first tiebreaker
                diff = min(abs(predicted_wins[name] - actual_wins) for name in tied)
                winners = [name for name in tied if abs(predicted_wins[name] - actual_wins) == diff]
                # division tiebreaker
                if len(winners) > 1:
                    actual_div_wins = sum(
                        (eagles_results[i] == 'W') if i < week_number else (outcome[i-week_number] == 'W')
                        for i in division_weeks
                    )
                    div_diff = min(abs(predicted_division_wins[name] - actual_div_wins) for name in winners)
                    winners = [name for name in winners if abs(predicted_division_wins[name] - actual_div_wins) == div_diff]
                # FINAL TIEBREAKER (Probabilistic): total points "closest" as a distribution
                weeks_remaining = total_weeks - week_number
                sd_per_game = 11.0  # tunable
                sd_remaining = max(1.0, sd_per_game * (weeks_remaining ** 0.5))
                mean_points = actual_points

                guesses_subset = {w: predicted_points[w] for w in winners}
                shares = closest_shares_normal(guesses_subset, mean_points, sd_remaining)

                for w in winners:
                    if is_weighted:
                        weighted_tally[w] += chance * 100 * shares[w]
                    else:
                        straight_tally[w] += shares[w]
                return  # allocation done for this outcome
        simulate(True)
        simulate(False)

    weighted_list = [round(weighted_tally[name],1) for name in picks_dict]
    straight_list = [round((straight_tally[name]/len(outcomes))*100,1) for name in picks_dict]

    return {"weighted": weighted_list, "straight": straight_list}
# --- END: Simulation API function ---