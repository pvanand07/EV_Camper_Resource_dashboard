/**
 * Client-side validation tests (mirrors static/v0/0.4.html validateInputs).
 * Run: node tests/test_client_validation.mjs
 */

const TANK_RULES = [
  { capacityField: 'fresh_capacity_gal', currentField: 'current_fresh_gal',
    capacityErrorKey: 'fresh_capacity', levelErrorKey: 'fresh' },
  { capacityField: 'grey_capacity_gal', currentField: 'current_grey_gal',
    capacityErrorKey: 'grey_capacity', levelErrorKey: 'grey' },
  { capacityField: 'black_capacity_gal', currentField: 'current_black_gal',
    capacityErrorKey: 'black_capacity', levelErrorKey: 'black' },
];

const coerceFloat = (v, def = 0) => {
  if (v === '' || v == null) return def;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : def;
};
const isBlank = (v) =>
  v === '' || v == null || v === undefined || (typeof v === 'number' && Number.isNaN(v));
const userTypeKey = (u) => `${u.name}::${u.is_child ? 1 : 0}`;
const behaviorFieldKey = (userType, field) => `${userType}::${field}`;
const activityFieldKey = (id, field) => `${id}::${field}`;

const NON_NEGATIVE_MSG = 'Must be zero or greater';
const LEVEL_NEGATIVE_MSG = 'Current level must be zero or greater';
const isNegative = (v) => !isBlank(v) && Number.isFinite(Number(v)) && Number(v) < 0;

function validateInputs(inputs) {
  const errors = { tank: {}, people: {}, behavior: {}, activity: {} };
  if (!inputs) return errors;

  const t = inputs.tank_environment;
  if (t) {
    for (const rule of TANK_RULES) {
      const cap = coerceFloat(t[rule.capacityField], 0);
      if (cap <= 0) {
        errors.tank[rule.capacityErrorKey] = 'Tank capacity must be greater than 0';
      }
      if (isBlank(t[rule.currentField])) {
        errors.tank[rule.levelErrorKey] = 'Current level is required';
      } else if (isNegative(t[rule.currentField])) {
        errors.tank[rule.levelErrorKey] = LEVEL_NEGATIVE_MSG;
      } else if (cap > 0 && coerceFloat(t[rule.currentField], 0) > cap) {
        errors.tank[rule.levelErrorKey] = `Exceeds capacity (${cap} gal)`;
      }
    }
    if (isBlank(t.climate_multiplier)) {
      errors.tank.climate_multiplier = 'Climate multiplier is required';
    } else if (coerceFloat(t.climate_multiplier, 0) <= 0) {
      errors.tank.climate_multiplier = 'Climate multiplier must be greater than 0';
    }
    if (isBlank(t.target_autonomy_days)) {
      errors.tank.target_autonomy = 'Target Autonomy Days is required';
    } else {
      const days = Number(t.target_autonomy_days);
      if (!Number.isFinite(days) || !Number.isInteger(days) || days < 1) {
        errors.tank.target_autonomy = 'Target Autonomy Days must be a whole number ≥ 1';
      }
    }
    const alertPct = (t.alert_threshold ?? 0.1) * 100;
    if (alertPct < 1) {
      errors.tank.alert_threshold = 'Minimum alert threshold is 1%.';
    } else if (alertPct > 99) {
      errors.tank.alert_threshold = 'Alert threshold cannot exceed 99%.';
    }
    if (t.drift_seed != null && t.drift_seed !== '' && Number(t.drift_seed) < 0) {
      errors.tank.drift_seed = NON_NEGATIVE_MSG;
    }
  }

  const types = inputs.user_types ?? [];
  let hasIndividualError = false;
  for (const u of types) {
    const v = Number(u.count);
    if (!Number.isFinite(v) || !Number.isInteger(v) || v < 0) {
      errors.people[userTypeKey(u)] = 'People count must be a non-negative integer';
      hasIndividualError = true;
    }
  }
  if (!hasIndividualError) {
    const total = types.reduce((s, u) => s + (Number(u.count) || 0), 0);
    if (total < 1) {
      const target = types.find(u => u.name === 'Adults Total') ?? types[0];
      if (target) {
        errors.people[userTypeKey(target)] = 'Add at least one person to compute a water plan';
      }
    }
  }

  for (const b of inputs.behavior_multipliers ?? []) {
    for (const field of ['shower_mult', 'sink_mult', 'toilet_mult']) {
      if (isNegative(b[field])) {
        errors.behavior[behaviorFieldKey(b.user_type, field)] = NON_NEGATIVE_MSG;
      }
    }
  }

  for (const a of inputs.activities ?? []) {
    for (const field of ['flow_gal_per_min', 'duration_min', 'events_per_day_per_person', 'gal_per_unit']) {
      if (isNegative(a[field])) {
        errors.activity[activityFieldKey(a.id, field)] = NON_NEGATIVE_MSG;
      }
    }
  }

  return errors;
}

const baseTank = {
  fresh_capacity_gal: 100,
  grey_capacity_gal: 80,
  black_capacity_gal: 40,
  current_fresh_gal: 100,
  current_grey_gal: 0,
  current_black_gal: 0,
  climate_multiplier: 1,
  target_autonomy_days: 5,
};

const basePeople = [
  { name: 'Expert', count: 2, is_child: 0 },
  { name: 'Typical', count: 0, is_child: 0 },
  { name: 'Glamper', count: 0, is_child: 0 },
  { name: 'Children', count: 0, is_child: 1 },
];

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg);
    process.exit(1);
  }
  console.log('OK:', msg);
}

// RIQA-37
const r37 = validateInputs({ tank_environment: { ...baseTank, target_autonomy_days: 7.5 }, user_types: basePeople });
assert(r37.tank.target_autonomy, 'RIQA-37: decimal target autonomy flagged');

// RIQA-38
const r38 = validateInputs({ tank_environment: { ...baseTank, current_fresh_gal: '' }, user_types: basePeople });
assert(r38.tank.fresh, 'RIQA-38: blank current fresh flagged');
const r38b = validateInputs({ tank_environment: { ...baseTank, climate_multiplier: '' }, user_types: basePeople });
assert(r38b.tank.climate_multiplier, 'RIQA-38: blank climate multiplier flagged');

// RIQA-39
const r39 = validateInputs({
  tank_environment: baseTank,
  user_types: [{ name: 'Expert', count: 1.5, is_child: 0 }, ...basePeople.slice(1)],
});
assert(r39.people['Expert::0'], 'RIQA-39: decimal occupant count flagged');

// Negative value validation
const rNegCap = validateInputs({ tank_environment: { ...baseTank, fresh_capacity_gal: -1 }, user_types: basePeople });
assert(rNegCap.tank.fresh_capacity, 'negative capacity flagged');

const rNegLevel = validateInputs({ tank_environment: { ...baseTank, current_fresh_gal: -1 }, user_types: basePeople });
assert(rNegLevel.tank.fresh === LEVEL_NEGATIVE_MSG, 'negative current level flagged');

const rBothNeg = validateInputs({
  tank_environment: { ...baseTank, fresh_capacity_gal: -1, current_fresh_gal: -1 },
  user_types: basePeople,
});
assert(rBothNeg.tank.fresh_capacity && rBothNeg.tank.fresh, 'both negative capacity and level flagged');

const rNegPeople = validateInputs({
  tank_environment: baseTank,
  user_types: [{ name: 'Expert', count: -1, is_child: 0 }, ...basePeople.slice(1)],
});
assert(rNegPeople.people['Expert::0'], 'negative people count flagged');

const rNegBehavior = validateInputs({
  tank_environment: baseTank,
  user_types: basePeople,
  behavior_multipliers: [{ user_type: 'Expert', shower_mult: -1, sink_mult: 1, toilet_mult: 1 }],
});
assert(rNegBehavior.behavior['Expert::shower_mult'], 'negative behavior multiplier flagged');

const rNegActivity = validateInputs({
  tank_environment: baseTank,
  user_types: basePeople,
  activities: [{ id: 1, name: 'Shower', flow_gal_per_min: -3, duration_min: 7, events_per_day_per_person: 1, gal_per_unit: null }],
});
assert(rNegActivity.activity['1::flow_gal_per_min'], 'negative activity value flagged');

// Valid baseline passes
const ok = validateInputs({ tank_environment: baseTank, user_types: basePeople });
assert(Object.keys(ok.tank).length === 0 && Object.keys(ok.people).length === 0, 'valid inputs pass');

console.log('\nAll client validation tests passed.');
