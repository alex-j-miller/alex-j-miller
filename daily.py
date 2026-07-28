import datetime
from dateutil import relativedelta
import requests
import os
from lxml import etree
import time
import hashlib
import json
from dotenv import load_dotenv

load_dotenv()

HEADERS = {'authorization': 'token ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME']
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'graph_commits': 0, 'loc_query': 0}


# ==================== Utility Functions ====================

def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def simple_request(func_name, query, variables):
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS)
    if request.status_code == 200:
        return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)


def perf_counter(funct, *args):
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def format_plural(unit):
    return 's' if unit != 1 else ''


def formatter(query_type, difference, funct_return=False, whitespace=0):
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    print('{:>12}'.format('%.4f' % difference + ' s ')) if difference > 1 else print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


# ==================== Data Fetching Functions ====================

def get_user_data(username):
    """Fetch user ID and account creation date"""
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request('get_user_data', query, variables)
    user_id = request.json()['data']['user']['id']
    created_at = request.json()['data']['user']['createdAt']
    return {'id': user_id}, created_at


def get_age_data(birthday):
    """Calculate age from birthday"""
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years),
        diff.months, 'month' + format_plural(diff.months),
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')


def get_commits_data(start_date, end_date, owner_id):
    """Fetch total commit count for date range"""
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    variables = {'start_date': start_date, 'end_date': end_date, 'login': USER_NAME}
    request = simple_request('get_commits_data', query, variables)
    response_data = request.json()

    if 'errors' in response_data:
        raise Exception('GraphQL error:', response_data['errors'])

    return int(response_data['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])


def get_followers_data(username):
    """Fetch follower count"""
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request('get_followers_data', query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def get_repos_count(owner_affiliation):
    """Fetch total repository count"""
    return _get_repos_data('repos', owner_affiliation)


def get_stars_count(owner_affiliation):
    """Fetch total stars across repositories"""
    return _get_repos_data('stars', owner_affiliation)


def _get_repos_data(count_type, owner_affiliation, cursor=None):
    """Helper function to fetch repos and stars using pagination"""
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request('_get_repos_data', query, variables)

    if count_type == 'repos':
        return request.json()['data']['user']['repositories']['totalCount']
    elif count_type == 'stars':
        total_stars = 0
        edges = request.json()['data']['user']['repositories']['edges']
        for node in edges:
            if node and node.get('node') and node['node'].get('stargazers'):
                total_stars += node['node']['stargazers']['totalCount']
        if request.json()['data']['user']['repositories']['pageInfo']['hasNextPage']:
            total_stars += _get_repos_data(count_type, owner_affiliation, request.json()['data']['user']['repositories']['pageInfo']['endCursor'])
        return total_stars


def get_loc_data(owner_affiliation, comment_size=0, force_cache=False, owner_id=None):
    """Fetch and cache lines of code data"""
    edges = _fetch_all_repos(owner_affiliation, [])
    return _build_cache(edges, comment_size, force_cache, owner_id), edges


def _fetch_all_repos(owner_affiliation, edges, cursor=None):
    """Recursively fetch all repositories with pagination"""
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        isPrivate
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request('_fetch_all_repos', query, variables)

    edges += request.json()['data']['user']['repositories']['edges']
    if request.json()['data']['user']['repositories']['pageInfo']['hasNextPage']:
        return _fetch_all_repos(owner_affiliation, edges, request.json()['data']['user']['repositories']['pageInfo']['endCursor'])
    return edges


def _build_cache(edges, comment_size, force_cache, owner_id, loc_add=0, loc_del=0):
    """Build and update cache file"""
    cached = True
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.json'

    try:
        with open(filename, 'r') as f:
            cache_data = json.load(f)
    except FileNotFoundError:
        cache_data = {'comment': ['This is a comment block. Write whatever you want here.'] * comment_size, 'repositories': []}
        with open(filename, 'w') as f:
            json.dump(cache_data, f, indent=2)

    if len(cache_data['repositories']) != len(edges) or force_cache:
        cached = False
        _flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f:
            cache_data = json.load(f)

    repo_dict = {repo['hash']: repo for repo in cache_data['repositories']}

    for edge in edges:
        repo_name = edge['node']['nameWithOwner']
        repo_hash = hashlib.sha256(repo_name.encode('utf-8')).hexdigest()

        if repo_hash in repo_dict and edge['node']['defaultBranchRef'] is not None:
            try:
                cached_commit_count = repo_dict[repo_hash]['commit_count']
                actual_commit_count = edge['node']['defaultBranchRef']['target']['history']['totalCount']

                if cached_commit_count != actual_commit_count:
                    cached = False
                    owner, repo_name_only = repo_name.split('/')
                    loc = _get_repo_loc(owner, repo_name_only, owner_id)
                    repo_dict[repo_hash]['commit_count'] = actual_commit_count
                    repo_dict[repo_hash]['my_commits'] = loc[2]
                    repo_dict[repo_hash]['additions'] = loc[0]
                    repo_dict[repo_hash]['deletions'] = loc[1]
            except (TypeError, KeyError):
                repo_dict[repo_hash].update({'commit_count': 0, 'my_commits': 0, 'additions': 0, 'deletions': 0})
        elif repo_hash in repo_dict and edge['node']['defaultBranchRef'] is None:
            repo_dict[repo_hash].update({'commit_count': 0, 'my_commits': 0, 'additions': 0, 'deletions': 0})

    cache_data['repositories'] = list(repo_dict.values())
    with open(filename, 'w') as f:
        json.dump(cache_data, f, indent=2)

    for repo in cache_data['repositories']:
        loc_add += repo['additions']
        loc_del += repo['deletions']

    return [loc_add, loc_del, loc_add - loc_del, cached]


def _get_repo_loc(owner, repo_name, owner_id, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """Recursively fetch lines of code for a repository"""
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS)

    if request.status_code == 200:
        if request.json()['data']['repository']['defaultBranchRef'] is not None:
            history = request.json()['data']['repository']['defaultBranchRef']['target']['history']
            for node in history['edges']:
                if node['node']['author']['user'] == owner_id:
                    my_commits += 1
                    addition_total += node['node']['additions']
                    deletion_total += node['node']['deletions']

            if history['edges'] and history['pageInfo']['hasNextPage']:
                return _get_repo_loc(owner, repo_name, owner_id, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])
            return addition_total, deletion_total, my_commits
        return 0
    raise Exception('_get_repo_loc has failed with', request.status_code, request.text)


def _flush_cache(edges, filename, comment_size):
    """Reset cache file"""
    cache_data = {
        'comment': ['This is a comment block. Write whatever you want here.'] * comment_size,
        'repositories': [
            {
                'hash': hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest(),
                'name': node['node']['nameWithOwner'],
                'commit_count': 0,
                'my_commits': 0,
                'additions': 0,
                'deletions': 0
            }
            for node in edges
        ]
    }
    with open(filename, 'w') as f:
        json.dump(cache_data, f, indent=2)


def get_commit_counter(comment_size):
    """Count total commits from cache"""
    total_commits = 0
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.json'
    with open(filename, 'r') as f:
        cache_data = json.load(f)
    for repo in cache_data['repositories']:
        total_commits += repo['my_commits']
    return total_commits


# ==================== Data Aggregation ====================

def get_ssh_stats_cache():
    """Load cached SSH stats if available"""
    cache_file = 'cache/ssh_stats_cache.json'
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cache = json.load(f)
            return cache.get('totals', {
                'commits': 0,
                'additions': 0,
                'deletions': 0,
                'net_loc': 0,
                'current_loc': 0,
            })
        except:
            pass
    return None


def collect_all_data(birthday, comment_size=7):
    """Collect all user data from GitHub"""
    owner_id, acc_date = get_user_data(USER_NAME)

    age_data = get_age_data(birthday)

    loc_data, loc_edges = get_loc_data(['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], comment_size, owner_id=owner_id)

    # Get all-time commits from cache
    commit_counter = get_commit_counter(comment_size)

    stars_data = get_stars_count(['OWNER'])

    repos_data = get_repos_count(['OWNER'])

    contrib_data = get_repos_count(['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])

    followers_data = get_followers_data(USER_NAME)

    # Load SSH stats if available
    ssh_stats = get_ssh_stats_cache()
    if ssh_stats:
        loc_data[0] += ssh_stats.get('additions', 0)
        loc_data[1] += ssh_stats.get('deletions', 0)
        loc_data[2] += ssh_stats.get('net_loc', 0)
        commit_counter += ssh_stats.get('commits', 0)

    return {
        'owner_id': owner_id,
        'age': age_data,
        'commits': commit_counter,
        'loc': loc_data,
        'total_commits': commit_counter,
        'stars': stars_data,
        'repos': repos_data,
        'contrib': contrib_data,
        'followers': followers_data,
        'loc_edges': loc_edges,
    }


# ==================== SVG Update Functions ====================

def update_svg(filename, data):
    """Update SVG file with collected data"""
    tree = etree.parse(filename)
    root = tree.getroot()

    _justify_format(root, 'commit_data', data['commits'], 18)
    _justify_format(root, 'star_data', data['stars'], 19)
    _justify_format(root, 'repo_data', data['repos'], 4)
    _justify_format(root, 'contrib_data', data['contrib'])
    _justify_format(root, 'follower_data', data['followers'], 15)
    _justify_format(root, 'loc_data', data['loc'][2], 13)
    _justify_format(root, 'loc_add', data['loc'][0])
    _justify_format(root, 'loc_del', data['loc'][1], 7)

    tree.write(filename, encoding='utf-8', xml_declaration=True)


def _justify_format(root, element_id, new_text, length=0):
    """Update SVG element with justified text"""
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    _find_and_replace(root, element_id, new_text)

    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: '', 1: ' ', 2: '. '}
        dot_string = dot_map[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    _find_and_replace(root, f"{element_id}_dots", dot_string)


def _find_and_replace(root, element_id, new_text):
    """Find and replace SVG element text"""
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def print_loc_per_repo(edges, comment_size):
    """Print lines of code per repository"""
    print('\nLines of code per repository:')
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.json'
    with open(filename, 'r') as f:
        cache_data = json.load(f)

    repo_dict = {repo['hash']: repo for repo in cache_data['repositories']}

    repos_data = []

    # Add API repos
    for edge in edges:
        repo_name = edge['node']['nameWithOwner']
        repo_hash = hashlib.sha256(repo_name.encode('utf-8')).hexdigest()
        if repo_hash in repo_dict:
            repo = repo_dict[repo_hash]
            net_loc = repo['additions'] - repo['deletions']
            repos_data.append((repo_name, net_loc))

    # Add SSH repos from cache
    ssh_cache_file = 'cache/ssh_stats_cache.json'
    if os.path.exists(ssh_cache_file):
        try:
            with open(ssh_cache_file, 'r') as f:
                ssh_cache = json.load(f)
            for repo in ssh_cache.get('repos', []):
                repo_name = repo['url'].split('/')[-1].replace('.git', '')
                net_loc = repo['net_loc']
                repos_data.append((repo_name, net_loc))
        except:
            pass

    if repos_data:
        repos_data.sort(key=lambda x: x[0])  # Sort by name
        max_name_len = max(len(name) for name, _ in repos_data)
        for repo_name, net_loc in repos_data:
            print(f'  {repo_name:<{max_name_len}} {net_loc:>12,}')


# ==================== Main ====================

if __name__ == '__main__':
    print('Calculation times:')

    data, collect_time = perf_counter(collect_all_data, datetime.datetime(2003, 3, 19))
    formatter('all data', collect_time)

    data['loc'][0] = '{:,}'.format(data['loc'][0])
    data['loc'][1] = '{:,}'.format(data['loc'][1])

    update_svg('dark_mode.svg', data)
    update_svg('light_mode.svg', data)

    print_loc_per_repo(data['loc_edges'], 7)
    print(f"\nTotal GitHub GraphQL API calls: {sum(QUERY_COUNT.values())}")
    for funct_name, count in QUERY_COUNT.items():
        print(f"   {funct_name}: {count}")
