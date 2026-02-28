"""
Copilot Basics — Onboarding Q&A
How to provision a DevPod virtual lab environment.
"""

ANSWERS = {
    'copilot-basics-onboarding-overview': (
        "To provision your DevPod virtual lab, start in the Cloud Portal. "
        "From the main dashboard, click the <strong>New Environment</strong> "
        "tile. In the search bar, type <strong>DevPod</strong> or enter "
        "catalog code <strong>DP-4090</strong>. Select "
        "<strong>DevPod Standard Tier</strong> from the results.\n\n"
        "On the Environment Configuration page, click "
        "<strong>Create Instance</strong> and confirm your team name and "
        "project ID in the Owner field. Under Resource Allocation, type "
        "<strong>Standard</strong> and select "
        "<strong>4 vCPU / 16 GB RAM / 100 GB SSD</strong>. Then scroll "
        "to Networking and Access to finalize your DevPod provisioning "
        "request.\n\n"
        "<strong>Quick Reference:</strong>\n"
        "1. Open <strong>Cloud Portal</strong> → click "
        "<strong>New Environment</strong>\n"
        "2. Search <strong>DevPod</strong> or catalog code "
        "<strong>DP-4090</strong>\n"
        "3. Select <strong>DevPod Standard Tier</strong>\n"
        "4. Click <strong>Create Instance</strong> → verify team/project\n"
        "5. Resource: <strong>4 vCPU / 16 GB RAM / 100 GB SSD</strong>\n"
        "6. Complete <strong>Networking and Access</strong> setup\n\n"
        "Watch the walkthrough video below for a step-by-step demonstration."
    ),
    'copilot-basics-onboarding-mytechhub': (
        "The Cloud Portal is your starting point for provisioning a DevPod "
        "environment. Navigate to the main dashboard and click the "
        "<strong>New Environment</strong> tile to begin. This is where all "
        "virtual lab requests, including DevPod instances, are submitted "
        "within the organization."
    ),
    'copilot-basics-onboarding-sealid': (
        "You can find DevPod by searching for <strong>DevPod</strong> "
        "in the Cloud Portal search bar, or by entering catalog code "
        "<strong>DP-4090</strong> directly. From the results, select "
        "<strong>DevPod Standard Tier</strong> to proceed to the "
        "Environment Configuration page where you can provision your lab."
    ),
    'copilot-basics-onboarding-instance': (
        "When provisioning your DevPod, go to the Resource Allocation "
        "section and type <strong>Standard</strong> in the Tier field, "
        "then press Enter. From the list that appears, select "
        "<strong>4 vCPU / 16 GB RAM / 100 GB SSD</strong>. This is "
        "the recommended configuration for standard development "
        "workloads and lab exercises."
    ),
    'copilot-basics-onboarding-summary': (
        "This video walks you through the full process of provisioning "
        "a DevPod virtual lab. It starts in the Cloud Portal on the "
        "main dashboard, where you click the New Environment tile. From "
        "there you search for DevPod or enter catalog code DP-4090 and "
        "select DevPod Standard Tier. On the Configuration page you "
        "create an instance, confirm your team and project ID, then "
        "pick the correct resource allocation – 4 vCPU, 16 GB RAM, "
        "100 GB SSD. The video finishes with the Networking and Access "
        "section where you complete and submit your provisioning request."
    ),
}

# Video metadata — maps answer IDs to video info
VIDEOS = {
    'copilot-basics-onboarding-overview': {
        'src': 'modules/copilot-basics/onboarding/github-onboarding.mp4',
        'label': 'DevPod Onboarding Walkthrough',
        'moduleUrl': '/modules/copilot-basics/onboarding',
    },
}

SUGGESTIONS = [
    {'text': 'How do I provision a DevPod?',
     'keywords': ['provision', 'devpod', 'virtual lab', 'request', 'access']},
    {'text': 'Where do I start in Cloud Portal?',
     'keywords': ['cloud portal', 'portal', 'where', 'start']},
    {'text': 'What is the catalog code for DevPod?',
     'keywords': ['catalog', 'code', 'number', 'dp-4090']},
    {'text': 'Which resource tier do I select for DevPod?',
     'keywords': ['resource', 'tier', 'select', 'allocation']},
]

QA_ENTRIES = [
    {
        'keywords': ['summarize', 'summary', 'video', 'section', 'overview',
                     'what is this', 'about', 'high level', 'recap',
                     'onboarding', 'walkthrough'],
        'answer': 'copilot-basics-onboarding-summary',
    },
    {
        'keywords': ['provision', 'access', 'get', 'devpod', 'virtual lab',
                     'onboarding', 'onboard',
                     'set up', 'setup', 'start', 'enable', 'activate',
                     'quick', 'reference', 'steps', 'checklist'],
        'answer': 'copilot-basics-onboarding-overview',
    },
    {
        'keywords': ['cloud portal', 'portal', 'dashboard',
                     'new environment', 'where', 'begin'],
        'answer': 'copilot-basics-onboarding-mytechhub',
    },
    {
        'keywords': ['catalog', 'code', 'catalog code', 'dp-4090', 'search',
                     'find', 'devpod standard', 'standard tier'],
        'answer': 'copilot-basics-onboarding-sealid',
    },
    {
        'keywords': ['resource', 'allocation', 'tier', 'vcpu', 'ram',
                     'ssd', 'select', 'pick', 'choose'],
        'answer': 'copilot-basics-onboarding-instance',
    },
]

NEXT_QUESTIONS = {
    'copilot-basics-onboarding-overview': [
        'How do I navigate the Cloud Portal dashboard?',
        'What catalog code do I search for?',
        'Which resource tier should I choose?',
    ],
    'copilot-basics-onboarding-mytechhub': [
        'What is the catalog code for DevPod?',
        'What is the recommended resource allocation?',
        'Walk me through the full provisioning process',
    ],
    'copilot-basics-onboarding-sealid': [
        'Which resource tier do I select?',
        'List the provisioning steps',
        'Summarize the onboarding video',
    ],
    'copilot-basics-onboarding-instance': [
        'How do I open the Cloud Portal environment tile?',
        'Recap the onboarding walkthrough',
        'How do I provision a DevPod?',
    ],
    'copilot-basics-onboarding-summary': [
        'Where do I start in Cloud Portal?',
        'What resource tier is recommended?',
        'Outline the key onboarding steps',
    ],
}
