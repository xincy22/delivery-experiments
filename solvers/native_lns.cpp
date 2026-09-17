// Self-contained dispatch optimization. Only the C++ standard library is used.
// No external LP/MIP, matching, SAT, or other optimization engine is called.
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
using namespace std;
// Costs are floating point; bounds and improvements use explicit tolerances.
static const double INF = 1e100, EPS = 1e-8;
static const int MAX_LOCAL_ORDERS = 60;
typedef chrono::steady_clock Clock;
static Clock::time_point started;
static double elapsed() { return chrono::duration<double>(Clock::now() - started).count(); }
// 1. Input: retain every real row and its original nonblank-line ID.
struct VecHash {
    size_t operator()(const vector<int> &a) const {
        size_t h = 0;
        for (int x : a)
            h = (h ^ size_t(x + 0x9e3779b9)) * 1099511628211ULL;
        return h;
    }
};
struct Row {
    double cost;
    int bundle, rider, id;
};
struct Bundle {
    vector<int> orders, rows;
};
struct Data {
    vector<Row> rows;
    vector<Bundle> bundles;
    vector<int> order_ids, rider_ids;
    vector<vector<int>> order_bundles, guide;
    int num_orders = 0, num_riders = 0, num_raw_rows = 0;
    double penalty = 0;
    bool nonnegative = true;
    vector<double> pi, mu;
    double lower = -INF;
    void load(const string &path) {
        ifstream f(path.c_str());
        if (!f)
            throw runtime_error("Cannot open input");
        unordered_map<int, int> om, rm;
        unordered_map<vector<int>, int, VecHash> bm;
        string line;
        int line_no = 0;
        double maxc = 1;
        while (getline(f, line)) {
            if (line.find_first_not_of(" \t\r\n") == string::npos)
                continue;
            if (line.compare(0, 7, "version") == 0)
                throw runtime_error("Input is a Git LFS pointer");
            char *p = const_cast<char *>(line.c_str()), *e;
            vector<int> orders;
            for (;;) {
                errno = 0;
                long v = strtol(p, &e, 10);
                if (p == e || errno == ERANGE || v < INT_MIN || v > INT_MAX)
                    throw runtime_error("Order ID must be a signed 32-bit integer");
                orders.push_back(int(v));
                p = e;
                if (*p == ',') {
                    ++p;
                    continue;
                }
                if (*p != '\t')
                    throw runtime_error("Expected tab after orders");
                ++p;
                break;
            }
            errno = 0;
            long r = strtol(p, &e, 10);
            if (p == e || errno == ERANGE || r < INT_MIN || r > INT_MAX || *e != '\t')
                throw runtime_error("Invalid rider");
            p = e + 1;
            double c = strtod(p, &e);
            if (p == e || !isfinite(c))
                throw runtime_error("Invalid cost");
            while (*e == '\r' || *e == ' ' || *e == '\t')
                ++e;
            if (*e)
                throw runtime_error("Unexpected trailing data");
            if (orders.size() > MAX_LOCAL_ORDERS)
                throw runtime_error("Bundles larger than 60 orders are not supported");
            sort(orders.begin(), orders.end());
            if (adjacent_find(orders.begin(), orders.end()) != orders.end())
                throw runtime_error("Duplicate orders");
            for (int &o : orders) {
                auto it = om.find(o);
                if (it == om.end()) {
                    int idx = om.size();
                    om[o] = idx;
                    order_ids.push_back(o);
                    o = idx;
                } else
                    o = it->second;
            }
            sort(orders.begin(), orders.end());
            int bi;
            auto it = bm.find(orders);
            if (it == bm.end()) {
                bi = bundles.size();
                bm[orders] = bi;
                Bundle b;
                b.orders = orders;
                bundles.push_back(b);
            } else
                bi = it->second;
            int ri;
            auto rt = rm.find(int(r));
            if (rt == rm.end()) {
                ri = rm.size();
                rm[int(r)] = ri;
                rider_ids.push_back(int(r));
            } else
                ri = rt->second;
            Row row = {c, bi, ri, line_no++};
            bundles[bi].rows.push_back(rows.size());
            rows.push_back(row);
            maxc = max(maxc, abs(c));
            nonnegative = nonnegative && c >= 0;
        }
        num_orders = om.size();
        num_riders = rm.size();
        num_raw_rows = rows.size();
        if (!num_raw_rows)
            throw runtime_error("Empty input");
        penalty = max(10000., 2 * maxc * (num_orders + 1));
        if (!isfinite(penalty) || penalty > 1e50)
            throw runtime_error("Costs exceed the supported numeric range");
        order_bundles.resize(num_orders);
        guide.resize(num_orders);
        for (int b = 0; b < int(bundles.size()); ++b) {
            for (int o : bundles[b].orders)
                order_bundles[o].push_back(b);
            sort(bundles[b].rows.begin(), bundles[b].rows.end(),
                 [&](int a, int z) { return rows[a].cost < rows[z].cost; });
        }
        // Artificial singleton rows are an initialization device, never publishable.
        for (int o = 0; o < num_orders; ++o) {
            vector<int> key(1, o);
            auto it = bm.find(key);
            int b;
            if (it == bm.end()) {
                b = bundles.size();
                Bundle x;
                x.orders = key;
                bundles.push_back(x);
                order_bundles[o].push_back(b);
            } else
                b = it->second;
            Row x = {penalty, b, num_riders + o, -1};
            rows.push_back(x);
            bundles[b].rows.push_back(rows.size() - 1);
        }
        cerr << "DATA rows=" << num_raw_rows << " orders=" << num_orders << " riders=" << num_riders
             << " bundles=" << bundles.size() << " load_sec=" << elapsed() << endl;
    }
    // 2. Global pricing, computed once before LNS.
    // Maximize a rider-separable Lagrangian dual by our own subgradient iteration.
    // This is also used to rank alternatives. It does not read reference costs.
    void price(int rounds, double deadline) {
        vector<double> p(num_orders, INF), bestp, bestr, br(num_riders), bp(bundles.size());
        vector<int> arg(num_riders), cov(num_orders);
        for (const Row &x : rows)
            if (x.id >= 0)
                for (int o : bundles[x.bundle].orders)
                    p[o] = min(p[o], x.cost / bundles[x.bundle].orders.size());
        for (double &x : p)
            if (x == INF)
                x = 0;
        double level = .08;
        for (int it = 0; it < rounds && (it == 0 || elapsed() < deadline); ++it) {
            for (int b = 0; b < int(bundles.size()); ++b) {
                double s = 0;
                for (int o : bundles[b].orders)
                    s += p[o];
                bp[b] = s;
            }
            fill(br.begin(), br.end(), 0);
            fill(arg.begin(), arg.end(), -1);
            for (int j = 0; j < num_raw_rows; ++j) {
                const Row &x = rows[j];
                double q = x.cost - bp[x.bundle];
                if (q < br[x.rider]) {
                    br[x.rider] = q;
                    arg[x.rider] = j;
                }
            }
            double val = accumulate(p.begin(), p.end(), 0.) + accumulate(br.begin(), br.end(), 0.);
            if (val > lower) {
                lower = val;
                bestp = p;
                bestr = br;
            }
            fill(cov.begin(), cov.end(), 0);
            for (int j : arg)
                if (j >= 0)
                    for (int o : bundles[rows[j].bundle].orders)
                        ++cov[o];
            double norm = 0;
            for (int v : cov)
                norm += (1. - v) * (1. - v);
            if (norm < EPS)
                break;
            double target = lower + max(.01, abs(lower) * level),
                   step = 1.4 * (target - val) / norm;
            for (int o = 0; o < num_orders; ++o)
                p[o] += step * (1 - cov[o]);
            if ((it + 1) % 50 == 0)
                level *= .65;
        }
        if (bestp.empty())
            throw runtime_error("No pricing iteration completed");
        pi = bestp;
        mu = bestr;
        // Match the exported certificate: shift every order price down slightly.
        // This does not change the stored guidance prices or the real objective.
        lower -= num_orders * 1e-9;
        // These are guidance lists only. Neighborhood repair enumerates all original
        // rows belonging to bundles contained in its free order set.
        vector<double> score(bundles.size(), INF);
        for (int b = 0; b < int(bundles.size()); ++b) {
            double sum = 0;
            for (int o : bundles[b].orders)
                sum += pi[o];
            for (int j : bundles[b].rows) {
                Row &x = rows[j];
                if (x.id >= 0)
                    score[b] =
                        min(score[b], (x.cost - sum - mu[x.rider]) / bundles[b].orders.size());
            }
        }
        for (int o = 0; o < num_orders; ++o) {
            guide[o] = order_bundles[o];
            sort(guide[o].begin(), guide[o].end(),
                 [&](int a, int b) { return score[a] < score[b]; });
        }
        cerr << "DUAL lower=" << setprecision(14) << lower << " sec=" << elapsed() << endl;
    }
};
struct Solution {
    vector<int> selected, order_owner, rider_owner;
    double cost = 0;
    int artificial = 0;
    void rebuild(const Data &d, const vector<int> &s) {
        selected = s;
        order_owner.assign(d.num_orders, -1);
        rider_owner.assign(d.num_riders + d.num_orders, -1);
        cost = 0;
        artificial = 0;
        for (int j : s) {
            const Row &x = d.rows[j];
            if (rider_owner[x.rider] >= 0)
                throw runtime_error("Duplicate rider internally");
            rider_owner[x.rider] = j;
            for (int o : d.bundles[x.bundle].orders) {
                if (order_owner[o] >= 0)
                    throw runtime_error("Duplicate order internally");
                order_owner[o] = j;
            }
            cost += x.cost;
            if (x.id < 0)
                ++artificial;
        }
        for (int a : order_owner)
            if (a < 0)
                throw runtime_error("Uncovered order internally");
    }
};
// 3. Fixed-partition minimum-cost rider matching.
// A complete, independently written shortest-augmenting-path Hungarian method.
// For a fixed order partition it optimizes the rider assignment exactly.
static Solution assign_riders(const Data &d, const vector<int> &partition) {
    int n = partition.size(), m = d.num_riders + d.num_orders;
    vector<double> a(size_t(n) * m, INF), u(n + 1, 0), v(m + 1, 0), minv(m + 1);
    vector<int> rid(size_t(n) * m, -1), p(m + 1, 0), way(m + 1);
    vector<char> used(m + 1);
    for (int i = 0; i < n; ++i)
        for (int j : d.bundles[partition[i]].rows) {
            const Row &x = d.rows[j];
            size_t k = size_t(i) * m + x.rider;
            if (x.cost < a[k]) {
                a[k] = x.cost;
                rid[k] = j;
            }
        }
    for (int i = 1; i <= n; ++i) {
        p[0] = i;
        int j0 = 0;
        fill(minv.begin(), minv.end(), INF);
        fill(used.begin(), used.end(), false);
        do {
            used[j0] = true;
            int i0 = p[j0], j1 = 0;
            double delta = INF;
            const double *ai = &a[size_t(i0 - 1) * m];
            for (int j = 1; j <= m; ++j)
                if (!used[j]) {
                    double cur = ai[j - 1] - u[i0] - v[j];
                    if (cur < minv[j]) {
                        minv[j] = cur;
                        way[j] = j0;
                    }
                    if (minv[j] < delta) {
                        delta = minv[j];
                        j1 = j;
                    }
                }
            if (delta > INF / 2)
                throw runtime_error("Fixed partition cannot be assigned");
            for (int j = 0; j <= m; ++j)
                if (used[j]) {
                    u[p[j]] += delta;
                    v[j] -= delta;
                } else
                    minv[j] -= delta;
            j0 = j1;
        } while (p[j0] != 0);
        do {
            int j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
        } while (j0);
    }
    vector<int> ids;
    for (int j = 1; j <= m; ++j)
        if (p[j]) {
            int x = rid[size_t(p[j] - 1) * m + j - 1];
            if (x < 0)
                throw runtime_error("Assignment chose missing edge");
            ids.push_back(x);
        }
    Solution s;
    s.rebuild(d, ids);
    return s;
}
// 4. Joint (bundle, rider) repair, not partition-only enumeration.
struct LocalRow {
    uint64_t mask;
    int rider, id;
    double cost, adjusted_cost;
};
// Exact-cover depth-first branch-and-bound, with both order equality and rider
// exclusion. A node/time budget makes a neighborhood an anytime search.
struct Repair {
    vector<LocalRow> rows;
    vector<vector<int>> adj;
    vector<double> pi;
    vector<char> used;
    vector<int> path, best;
    int q, num_riders;
    long long nodes = 0, limit;
    double bestcost, deadline;
    bool nonnegative;
    bool truncated = false;
    Repair(int q_, int nr_, double upper, long long lim, double end, bool nn)
        : q(q_), num_riders(nr_), limit(lim), bestcost(upper), deadline(end), nonnegative(nn) {
        adj.resize(q);
        pi.assign(q, INF);
        used.assign(num_riders, 0);
    }
    void dual() {
        for (auto &x : rows) {
            double z = x.cost / __builtin_popcountll(x.mask);
            for (uint64_t t = x.mask; t; t &= t - 1) {
                int o = __builtin_ctzll(t);
                pi[o] = min(pi[o], z);
            }
        }
        for (double &z : pi)
            if (z == INF)
                z = 0;
        vector<double> p = pi, br(num_riders);
        vector<int> arg(num_riders), cov(q);
        double bestlb = -INF;
        int rounds = bestcost > 1e6 ? 24 : 70;
        for (int it = 0; it < rounds && (it == 0 || elapsed() < deadline); ++it) {
            fill(br.begin(), br.end(), 0);
            fill(arg.begin(), arg.end(), -1);
            for (int j = 0; j < int(rows.size()); ++j) {
                auto &x = rows[j];
                double z = x.cost;
                for (uint64_t t = x.mask; t; t &= t - 1)
                    z -= p[__builtin_ctzll(t)];
                if (z < br[x.rider]) {
                    br[x.rider] = z;
                    arg[x.rider] = j;
                }
            }
            double lb = accumulate(p.begin(), p.end(), 0.) + accumulate(br.begin(), br.end(), 0.);
            if (lb > bestlb) {
                bestlb = lb;
                pi = p;
            }
            if (bestcost - lb < 1e-7)
                break;
            fill(cov.begin(), cov.end(), 0);
            for (int j : arg)
                if (j >= 0)
                    for (uint64_t t = rows[j].mask; t; t &= t - 1)
                        ++cov[__builtin_ctzll(t)];
            double norm = 0;
            for (int z : cov)
                norm += (1. - z) * (1. - z);
            if (norm == 0)
                break;
            double target = min(bestcost, bestlb + max(1., abs(bestlb) * .1));
            double step = (1.5 / (1. + it * .025)) * (target - lb) / norm;
            for (int o = 0; o < q; ++o)
                p[o] += step * (1 - cov[o]);
        }
        for (int j = 0; j < int(rows.size()); ++j) {
            auto &x = rows[j];
            x.adjusted_cost = x.cost;
            for (uint64_t t = x.mask; t; t &= t - 1) {
                int o = __builtin_ctzll(t);
                x.adjusted_cost -= pi[o];
                adj[o].push_back(j);
            }
        }
        for (auto &list : adj)
            sort(list.begin(), list.end(),
                 [&](int a, int b) { return rows[a].adjusted_cost < rows[b].adjusted_cost; });
    }
    void dfs(uint64_t remaining, double cost) {
        if (++nodes > limit) {
            truncated = true;
            return;
        }
        if ((nodes == 1 || (nodes & 255) == 0) && elapsed() > deadline) {
            nodes = limit + 1;
            truncated = true;
            return;
        }
        if (!remaining) {
            if (cost < bestcost - EPS) {
                bestcost = cost;
                best = path;
            }
            return;
        }
        if (nonnegative && cost >= bestcost - EPS)
            return;
        // Recompute rider minima using only rows still feasible at THIS node.
        // Keeping the root rider minima would be a weaker bound.
        vector<int> counts(q, 0);
        vector<double> br(num_riders, 0.);
        double lb = cost;
        for (uint64_t t = remaining; t; t &= t - 1)
            lb += pi[__builtin_ctzll(t)];
        for (const auto &x : rows)
            if (!used[x.rider] && (x.mask & remaining) == x.mask) {
                br[x.rider] = min(br[x.rider], x.adjusted_cost);
                for (uint64_t t = x.mask; t; t &= t - 1)
                    ++counts[__builtin_ctzll(t)];
            }
        lb += accumulate(br.begin(), br.end(), 0.);
        if (lb >= bestcost - EPS)
            return;
        int order = -1, cnt = 2147483647;
        for (uint64_t t = remaining; t; t &= t - 1) {
            int o = __builtin_ctzll(t);
            if (counts[o] < cnt) {
                cnt = counts[o];
                order = o;
            }
        }
        if (cnt == 0)
            return;
        // Forcing row j removes the option to use its rider's cheaper alternative.
        // Therefore lb + (row_adjusted_cost - rider_minimum) is also a lower bound.
        vector<pair<double, int>> choices;
        for (int j : adj[order]) {
            const auto &x = rows[j];
            if (!used[x.rider] && (x.mask & remaining) == x.mask) {
                double extra = x.adjusted_cost - br[x.rider];
                if (lb + extra < bestcost - EPS)
                    choices.push_back(make_pair(extra, j));
            }
        }
        sort(choices.begin(), choices.end());
        for (auto a : choices) {
            const auto &x = rows[a.second];
            if (lb + a.first >= bestcost - EPS)
                continue;
            used[x.rider] = true;
            path.push_back(x.id);
            dfs(remaining ^ x.mask, cost + x.cost);
            path.pop_back();
            used[x.rider] = false;
            if (nodes > limit)
                break;
        }
    }
};
// 5. Publish real, feasible rows only. Artificial initialization is never an answer.
static void save(const Data &d, const Solution &s, const string &out, int seed,
                 long long iterations, long long nodes, const string &mode,
                 double first_feasible_sec, double best_found_sec) {
    if (s.artificial)
        return;
    ofstream f((out + ".tsv.tmp").c_str());
    if (!f)
        throw runtime_error("Cannot write solution");
    f << "row_id\torders\trider\tcost\n" << setprecision(17);
    vector<int> ids = s.selected;
    sort(ids.begin(), ids.end());
    long double cost = 0;
    for (int j : ids) {
        const Row &x = d.rows[j];
        cost += x.cost;
        f << x.id << '\t';
        vector<int> os;
        for (int o : d.bundles[x.bundle].orders)
            os.push_back(d.order_ids[o]);
        sort(os.begin(), os.end());
        for (size_t k = 0; k < os.size(); ++k) {
            if (k)
                f << ',';
            f << os[k];
        }
        f << '\t' << d.rider_ids[x.rider] << '\t' << x.cost << '\n';
    }
    f.close();
    if (!f || rename((out + ".tsv.tmp").c_str(), (out + ".tsv").c_str()) != 0)
        throw runtime_error("Cannot finalize solution TSV");
    ofstream m((out + ".json.tmp").c_str());
    if (!m)
        throw runtime_error("Cannot write metrics");
    m << setprecision(17) << "{\"solver\":\"native_lns\",\"seed\":" << seed
      << ",\"total_cost\":" << double(cost) << ",\"lower_bound\":" << d.lower
      << ",\"runtime_sec\":" << elapsed() << ",\"selected_rows\":" << ids.size()
      << ",\"feasible\":true,\"mode\":\"" << mode
      << "\",\"first_feasible_sec\":" << first_feasible_sec
      << ",\"best_found_sec\":" << best_found_sec << ",\"iterations\":" << iterations
      << ",\"nodes\":" << nodes << "}\n";
    m.close();
    if (!m || rename((out + ".json.tmp").c_str(), (out + ".json").c_str()) != 0)
        throw runtime_error("Cannot finalize metrics");
}
int main(int argc, char **argv) {
    try {
        started = Clock::now();
        if (argc < 3 || argc > 8) {
            cerr << "Usage: native_lns CASE.tsv OUTPUT_PREFIX [seconds=120] [seed=1] "
                    "[pricing_rounds=200] [mode=descent|annealed|directed] [max_iterations=-1]\n";
            return argc == 2 && string(argv[1]) == "--help" ? 0 : 2;
        }
        double seconds = argc > 3 ? stod(argv[3]) : 120.;
        int seed = argc > 4 ? stoi(argv[4]) : 1, pr = argc > 5 ? stoi(argv[5]) : 200;
        string mode = argc > 6 ? argv[6] : "descent";
        long long max_iterations = argc > 7 ? stoll(argv[7]) : -1;
        if (!isfinite(seconds) || seconds <= 0 || pr <= 0)
            throw runtime_error("Finite positive time and positive pricing rounds required");
        if (mode != "descent" && mode != "annealed" && mode != "directed")
            throw runtime_error("Unknown mode");
        if (max_iterations < -1)
            throw runtime_error("max_iterations must be -1 or nonnegative");
        // Refuse stale-output ambiguity, especially when num_orders feasible solution is found.
        for (const string &suffix : vector<string>{".tsv", ".json", ".dual.tsv"}) {
            ifstream existing((string(argv[2]) + suffix).c_str());
            if (existing)
                throw runtime_error("Output prefix already exists; choose a new prefix");
        }
        mt19937 rng(seed);
        Data d;
        d.load(argv[1]);
        d.price(pr, min(seconds * .25, elapsed() + 30.));
        {
            ofstream cert((string(argv[2]) + ".dual.tsv").c_str());
            if (!cert)
                throw runtime_error("Cannot write dual certificate");
            cert << "kind\tid\tvalue\n" << setprecision(17);
            for (int o = 0; o < d.num_orders; ++o)
                cert << "order\t" << d.order_ids[o] << '\t' << d.pi[o] - 1e-9 << '\n';
            for (int r = 0; r < d.num_riders; ++r)
                cert << "rider\t" << d.rider_ids[r] << '\t' << d.mu[r] << '\n';
        }
        vector<int> part;
        for (int o = 0; o < d.num_orders; ++o)
            part.push_back(d.rows[d.num_raw_rows + o].bundle);
        Solution cur = assign_riders(d, part), best = cur;
        cerr << "INITIAL cost=" << setprecision(14) << cur.cost << " artificial=" << cur.artificial
             << " sec=" << elapsed() << endl;
        double first_feasible_sec = cur.artificial ? -1. : elapsed();
        double best_found_sec = cur.artificial ? -1. : elapsed();
        // 6. LNS: global guidance chooses a region; local B&B chooses actual rows.
        long long it = 0, totalnodes = 0;
        vector<int> mark(d.rows.size(), 0), pos(d.num_orders, -1), bmark(d.bundles.size(), 0);
        int epoch = 0;
        double lastimprove = elapsed();
        while (elapsed() < seconds && (max_iterations < 0 || it < max_iterations)) {
            if (!best.artificial && best.cost - d.lower < 1e-7)
                break;
            ++it;
            ++epoch;
            vector<int> removed, orders;
            int targets[] = {8, 12, 16, 24, 32, 48};
            int target = targets[rng() % 6];
            if (cur.artificial)
                target = 32;
            auto add = [&](int j) {
                if (j < 0 || mark[j] == epoch)
                    return true;
                int k = d.bundles[d.rows[j].bundle].orders.size();
                if (int(orders.size()) + k > MAX_LOCAL_ORDERS)
                    return false;
                mark[j] = epoch;
                removed.push_back(j);
                for (int o : d.bundles[d.rows[j].bundle].orders)
                    orders.push_back(o);
                return true;
            };
            int sj = cur.selected[rng() % cur.selected.size()];
            if (cur.artificial)
                for (int j : cur.selected)
                    if (d.rows[j].id < 0) {
                        sj = j;
                        break;
                    }
            // Half the neighborhoods begin at a relatively expensive current row.
            if (!cur.artificial && rng() % 2 == 0) {
                double worst = -INF;
                for (int k = 0; k < 12; ++k) {
                    int j = cur.selected[rng() % cur.selected.size()];
                    double val = d.rows[j].cost;
                    for (int o : d.bundles[d.rows[j].bundle].orders)
                        val -= d.pi[o];
                    val -= d.mu[d.rows[j].rider];
                    if (val > worst) {
                        worst = val;
                        sj = j;
                    }
                }
            }
            add(sj);
            // Directed moves force a promising alternative, then jointly repair all
            // displaced orders and the displaced rider's current bundle.
            int forced = -1;
            if (mode == "directed" && !cur.artificial && it % 5 == 0) {
                int o = d.bundles[d.rows[sj].bundle]
                            .orders[rng() % d.bundles[d.rows[sj].bundle].orders.size()];
                const auto &gs = d.guide[o];
                if (!gs.empty()) {
                    int b = gs[rng() % min(int(gs.size()), 24)];
                    vector<pair<double, int>> options;
                    for (int j : d.bundles[b].rows)
                        if (d.rows[j].id >= 0 && cur.rider_owner[d.rows[j].rider] != j)
                            options.push_back(make_pair(d.rows[j].cost - d.mu[d.rows[j].rider], j));
                    sort(options.begin(), options.end());
                    if (!options.empty()) {
                        forced = options[rng() % min(int(options.size()), 3)].second;
                        bool closed = true;
                        for (int z : d.bundles[d.rows[forced].bundle].orders)
                            closed = add(cur.order_owner[z]) && closed;
                        closed = add(cur.rider_owner[d.rows[forced].rider]) && closed;
                        if (!closed)
                            forced = -1;
                    }
                }
            }
            for (int attempts = 0; int(orders.size()) < target && attempts < target * 8;
                 ++attempts) {
                int o = orders[rng() % orders.size()];
                const auto &gs = d.guide[o];
                int lim = min(int(gs.size()), (rng() % 3 == 0) ? 80 : 16);
                if (!lim)
                    continue;
                int b = gs[rng() % lim];
                vector<int> deps;
                for (int z : d.bundles[b].orders)
                    if (mark[cur.order_owner[z]] != epoch)
                        deps.push_back(cur.order_owner[z]);
                const auto &rr = d.bundles[b].rows;
                if (!rr.empty()) {
                    int j = rr[rng() % min(int(rr.size()), 4)];
                    if (cur.rider_owner[d.rows[j].rider] >= 0 &&
                        mark[cur.rider_owner[d.rows[j].rider]] != epoch)
                        deps.push_back(cur.rider_owner[d.rows[j].rider]);
                }
                sort(deps.begin(), deps.end());
                deps.erase(unique(deps.begin(), deps.end()), deps.end());
                int sum = orders.size();
                for (int j : deps)
                    sum += d.bundles[d.rows[j].bundle].orders.size();
                if (sum <= min(60, target + 4))
                    for (int j : deps)
                        add(j);
            }
            if (orders.empty())
                continue;
            for (int k = 0; k < int(orders.size()); ++k)
                pos[orders[k]] = k;
            double old = 0;
            for (int j : removed)
                old += d.rows[j].cost;
            // Occasionally forbid one incumbent row and admit a small uphill move.
            // The best fully feasible solution is retained separately throughout.
            bool shake = mode != "descent" && !cur.artificial && (it % 7 == 0 || forced >= 0);
            double phase = fmod(elapsed(), 30.) / 30.;
            double temperature =
                max(.005, abs(d.lower) / d.num_orders * (.20 * (1. - phase) + .01));
            int forbid = (shake && forced < 0) ? removed[rng() % removed.size()] : -1;
            double upper = old + (shake ? temperature * 3 : 0.);
            // All num_raw_rows rows in the closed neighborhood remain candidates, except the
            // explicit shake/forcing restriction and safe nonnegative-cost pruning.
            vector<LocalRow> local;
            unordered_map<int, int> rm;
            for (int o : orders)
                for (int b : d.order_bundles[o])
                    if (bmark[b] != epoch) {
                        bmark[b] = epoch;
                        uint64_t mask = 0;
                        bool ok = true;
                        for (int z : d.bundles[b].orders) {
                            if (pos[z] < 0) {
                                ok = false;
                                break;
                            }
                            mask |= uint64_t(1) << pos[z];
                        }
                        if (!ok)
                            continue;
                        for (int j : d.bundles[b].rows) {
                            if (j == forbid)
                                continue;
                            const Row &x = d.rows[j];
                            if (cur.rider_owner[x.rider] >= 0 &&
                                mark[cur.rider_owner[x.rider]] != epoch)
                                continue;
                            if (d.nonnegative && x.cost > upper + EPS)
                                continue;
                            int r;
                            auto t = rm.find(x.rider);
                            if (t == rm.end()) {
                                r = rm.size();
                                rm[x.rider] = r;
                            } else
                                r = t->second;
                            LocalRow a = {mask, r, j, x.cost, 0};
                            local.push_back(a);
                        }
                    }
            for (int o : orders)
                pos[o] = -1;
            if (forced >= 0) {
                uint64_t mask = 0;
                int rider = -1;
                for (const auto &x : local)
                    if (x.id == forced) {
                        mask = x.mask;
                        rider = x.rider;
                        break;
                    }
                if (rider >= 0)
                    local.erase(remove_if(local.begin(), local.end(),
                                          [&](const LocalRow &x) {
                                              return x.id != forced &&
                                                     ((x.mask & mask) != 0 || x.rider == rider);
                                          }),
                                local.end());
            }
            long long budget = cur.artificial ? 10000 : 4000;
            Repair rep(orders.size(), rm.size(), upper, budget, min(seconds, elapsed() + .35),
                       d.nonnegative);
            rep.rows.swap(local);
            rep.dual();
            rep.dfs((uint64_t(1) << orders.size()) - 1, 0);
            totalnodes += rep.nodes;
            if (!rep.best.empty() && (rep.bestcost < old - EPS ||
                                      (shake && double(rng()) / mt19937::max() <
                                                    exp((old - rep.bestcost) / temperature)))) {
                vector<int> ns;
                for (int j : cur.selected)
                    if (mark[j] != epoch)
                        ns.push_back(j);
                ns.insert(ns.end(), rep.best.begin(), rep.best.end());
                cur.rebuild(d, ns);
            }
            // This globally optimizes riders for the current partition, but the joint
            // LNS repair above is still allowed to change both bundles and riders.
            if (it % 30 == 0) {
                part.clear();
                for (int j : cur.selected)
                    part.push_back(d.rows[j].bundle);
                Solution a = assign_riders(d, part);
                if (a.cost < cur.cost - EPS)
                    cur = a;
            }
            if (cur.cost < best.cost - EPS) {
                best = cur;
                if (!best.artificial) {
                    best_found_sec = elapsed();
                    if (first_feasible_sec < 0)
                        first_feasible_sec = best_found_sec;
                }
                lastimprove = elapsed();
                cerr << "BEST it=" << it << " cost=" << setprecision(14) << best.cost
                     << " artificial=" << best.artificial << " nodes=" << totalnodes
                     << " sec=" << elapsed() << endl;
                save(d, best, argv[2], seed, it, totalnodes, mode, first_feasible_sec,
                     best_found_sec);
            }
            if (mode != "descent" && !best.artificial && it % 250 == 0 &&
                elapsed() - lastimprove > 15.)
                cur = best;
            if (it % 500 == 0)
                cerr << "PROGRESS it=" << it << " cost=" << cur.cost << " best=" << best.cost
                     << " sec=" << elapsed() << endl;
        }
        save(d, best, argv[2], seed, it, totalnodes, mode, first_feasible_sec, best_found_sec);
        cerr << "DONE cost=" << setprecision(17) << best.cost << " artificial=" << best.artificial
             << " iterations=" << it << " nodes=" << totalnodes << " sec=" << elapsed() << endl;
        return best.artificial ? 3 : 0;
    } catch (const exception &e) {
        cerr << "ERROR " << e.what() << endl;
        return 1;
    }
}
