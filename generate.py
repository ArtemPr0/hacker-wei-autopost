#!/usr/bin/env python3
"""Writes and renders new carousels for every account that has a writer (Hacker Wei, Pirate Wei, The Only Wei), so no queue runs dry.

Each run, for each of those accounts: ask Google Gemini (free tier) to write up to MAX_PER_RUN carousels in that account's format,
check each against fixed rules, have a second AI pass edit-check it, render the 7 slides in the account's design, and add it to its queue.
The Only Wei never lets the AI choose or write the quote: quotes come from quotes.json (real, sourced) and are placed on the cover by code.
Any failure leaves the queue untouched (the daily post still goes out from what is already queued).

Env: GEMINI_API_KEY (free key from Google AI Studio). Optional: ACCOUNT (one account id), MODELS_URL, MODEL_IDS (comma separated), FORCE=1.
Flags: --from-file spec.json (skip the AI, used for tests), --dry-run (do not write into posts/).
"""
import os, sys, re, json, time, random, shutil, subprocess, tempfile, urllib.request, urllib.error
import common

ROOT = os.path.dirname(os.path.abspath(__file__))
POSTS = os.path.join(ROOT, "posts")      # these three are switched to the current account inside main()
TOPICS = os.path.join(ROOT, "state", "topics.json")
P = None                                 # the current account's writer profile
URL = os.environ.get("MODELS_URL", "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")
MODEL_IDS = [m.strip() for m in os.environ.get("MODEL_IDS", "").split(",") if m.strip()]
TARGET = 365        # safety valve only: stop writing once a full year of unposted carousels is waiting (keeps the GitHub repo a sane size)
MAX_PER_RUN = 2     # new carousels written per account per run (three runs a day; free tier: about 20 requests a day on the main model, 500 on the lite one)
ATTEMPTS = 4        # tries per carousel before giving up for the day
TIME_BUDGET = float(os.environ.get("TIME_BUDGET", "780"))   # seconds; stop starting new work after this, the rest waits for tomorrow
MAIN_BUDGET = 6     # max calls per run to the main (non-lite) model, to stay well inside its daily free limit
FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
AREAS = ["CVs", "cover letters and application forms", "online tests and video assessments", "interviews", "assessment centres",
         "networking and LinkedIn", "internships, placements and spring weeks", "graduate schemes and deadlines",
         "starting your first job", "workplace skills in your first year", "handling rejection and staying motivated",
         "job offers, contracts and negotiating", "using your university careers service", "turning part-time jobs and societies into experience",
         "organising your job search", "career changes and not knowing what you want to do", "emails and messages to employers",
         "references, right to work checks and onboarding"]

def log(*a): print(*a, flush=True)

RULES = """You are the head writer for "Hacker Wei", an Instagram account that gives UK university students and recent graduates practical job-hunting hacks. You write one 7-slide carousel at a time. Your work is published without a human editor, so it must be right first time.

AUDIENCE AND VOICE
- Readers are UK students and graduates aged 18 to 25 applying for internships, placements, graduate schemes and first jobs.
- Voice: a sharp, friendly older student who has been through it. Calm, practical, a little cheeky. Never preachy, never corporate.
- Plain words, short sentences, active verbs. One idea per line. No filler such as "in today's competitive market".

BRITISH ENGLISH ONLY
- British spelling: organise, summarise, prioritise, recognise, analyse, programme, colour, favourite, centre, behaviour, enrol, skilful, licence (noun), practise (verb) and practice (noun).
- UK terms: CV (never resume), university or uni (never college or school), graduate scheme, placement year, internship, assessment centre, careers service, mark or grade (never GPA), first year (never freshman), holiday (never vacation), maths, postcode.
- Write STAR in capitals when you mean the STAR method.

TRUTH AND SAFETY (most important)
- Practical advice only. No statistics, percentages, salaries, pay figures, dates, deadlines, study or survey claims, or anything presented as a researched fact.
- No promises ("guaranteed", "always works", "will get you hired"). Use honest wording: "often", "many", "can", "tends to".
- No legal, visa, tax or medical advice. No named companies except everyday tools (LinkedIn, Excel, Zoom, Teams, Google Docs).
- Advice must be honest and fair to employers. Never suggest lying, exaggerating, faking experience, using AI to cheat a test, or tricking anyone.
- No links, no @mentions, no hashtags and no emojis inside slide text. Never use em dashes or en dashes.

CAROUSEL FORMAT (exact)
Slide 1 is the cover. Slides 2 to 6 are five hacks. Slide 7 is the closing slide.
- "topic": 3 to 8 words naming the topic.
- "cmd": a fake terminal command, lowercase, one verb then one flag, like "scan --cv" or "send --thank-you" (max 26 characters).
- "head": the cover headline as 2 to 4 SHORT LINES IN CAPITALS. Each line max 13 characters including spaces. Together they read as one punchy claim or promise about the topic. Wrap exactly ONE word or short phrase in <g></g> (it is shown in lime green). Keep the <g> span inside a single line.
- "pill": cover sub-label that starts with "5 " and names what the reader gets, like "5 fixes that get you past it" (max 24 characters if head has 4 lines, otherwise max 34).
- "hacks": exactly 5 items. Each item is three strings:
    1. headline: an instruction that starts with a verb and ends with a full stop (12 to 34 characters), e.g. "Keep the layout boring."
    2. why: one sentence saying why it matters (max 75 characters).
    3. action: one concrete thing to do today, specific enough to copy (max 70 characters). Prefer an example in the action.
  The five hacks must be clearly different from each other, ordered so the carousel flows, and each must stand alone.
- "out": three strings for the closing slide:
    1. a question that starts with "Which" and can be answered with a number from 1 to 5, e.g. "Which one will you try first?" (max 26 characters)
    2. starts with "Save this " (max 30 characters)
    3. starts with "Send it to " (max 32 characters)
- "hook": the caption opener, one or two sentences that make the reader want to swipe (max 140 characters, no emojis, no hashtags).
- "hashtags": 9 lowercase hashtags without the # sign, letters and digits only: about 5 broad UK graduate tags and 4 topic tags.

GOLD STANDARD EXAMPLES (match this quality, structure and length; do not reuse these topics)
{"topic":"CV fixes for applicant tracking systems","cmd":"scan --cv","head":["A ROBOT OFTEN","READS YOUR","<g>CV</g> FIRST."],"pill":"5 fixes that get you past it","hacks":[["Copy the job ad's exact words.","Tracking systems and recruiters scan for the skills named in the advert.","If it says stakeholder management, write stakeholder management."],["Keep the layout boring.","Columns, text boxes and icons can get scrambled when software reads them.","One column, with standard headings: Education, Experience, Skills."],["Put numbers on your results.","Numbers show impact faster than a list of duties.","Swap \\"helped with events\\" for \\"ran 4 society events\\"."],["Tailor the top third.","Recruiters often skim the top of page one first.","Rewrite your profile and first bullets for each role."],["Name the file properly.","A tidy file name looks careful and is easy to find.","Firstname_Surname_CV.pdf, unless they ask for another format."]],"out":["Which fix did you skip?","Save this for application day","Send it to a friend with a CV"],"hook":"A robot often reads your CV before a human does. Here is how to get past it.","hashtags":["ukgraduate","graduatejobs","ukstudents","careeradvice","jobhunting","cvtips","cvhelp","graduatescheme","jobsearchuk"]}
{"topic":"What to do after a job rejection","cmd":"recover --rejection","head":["REJECTED?","DO THIS","<g>NEXT.</g>"],"pill":"5 moves that turn a no into a lead","hacks":[["Reply within 24 hours.","A polite reply keeps the door open.","Thank them. Keep it short and warm."],["Ask for feedback.","Not everyone replies, but the answers can be gold.","Ask: \\"Is there one thing I could improve for next time?\\""],["Ask to be kept in mind.","Roles open up again, and teams remember professional people.","Ask if you can stay in touch about future roles."],["Connect with the people you met.","A rejection is still a relationship.","Send a LinkedIn request with a one-line note."],["Log what you learned.","Patterns show you what to fix first.","Note the stage you reached and one thing to change."]],"out":["Which one will you try?","Save this for a rough day","Send it to a friend who needs it"],"hook":"A rejection is not the end. It can be a lead.","hashtags":["ukgraduate","graduatejobs","ukstudents","careeradvice","jobsearch","rejection","jobrejection","graduatelife","motivation"]}

BEFORE YOU ANSWER, CHECK YOUR OWN WORK
1. Count the characters of every line against its limit. Shorten anything over.
2. Is every spelling British and every term a UK term?
3. Is there any number, statistic, promise or company name that breaks the rules? Remove it.
4. Does each hack headline start with a verb, and does its action tell the reader exactly what to do?
5. Are the five hacks different from each other and from the already used topics?
6. Does the closing question start with "Which" and make sense with "Comment the number"?

Return ONLY the JSON object with exactly these keys: topic, cmd, head, pill, hacks, out, hook, hashtags. No commentary, no markdown."""

REVIEW = """You are a strict British sub-editor and an experienced UK university careers adviser. You are the last check before an Instagram carousel for UK students and graduates is published with no human editor.

Read the carousel JSON and fail it if ANY of these is true:
1. Any American spelling or American term (resume, college for university, GPA, freshman, vacation, practice used as a verb, organize, and so on), or any grammar or punctuation mistake.
2. Any hack is wrong, misleading, vague, unsafe, dishonest, unfair to employers, or would not work in the UK job market.
3. Any statistic, percentage, pay figure, date, invented fact, promise of results, legal, visa, tax or medical advice.
4. In any hack the headline, the why line and the action do not clearly belong together, or the action is not concrete enough to do today.
5. Two hacks say nearly the same thing, or a hack does not fit the topic.
6. The cover headline does not read naturally as one phrase, or does not match what the five hacks deliver.
7. The closing question cannot be answered with a number from 1 to 5.
8. Anything a careful editor at a UK careers service would not publish.

Be strict but fair: do not fail it for style preferences. Fail only for real problems a reader would notice or be misled by.
Return ONLY JSON: {"verdict": "pass" or "fail", "problems": ["field name: what is wrong and how to fix it", ...]} with at most 6 problems (an empty list on pass)."""

PIRATE_AREAS = ["job adverts and what they really mean", "being ghosted by recruiters", "entry-level jobs that want experience", "LinkedIn culture and humble bragging",
    "interview questions nobody answers honestly", "online tests and one-way video interviews", "assessment centres and group exercises",
    "careers advice that aged badly", "networking events and small talk", "unpaid work, trial tasks and exposure", "application forms that ask for your CV twice",
    "rejection emails and feedback that says nothing", "office buzzwords and corporate speak", "graduate scheme hype", "CV myths that will not die",
    "the hidden job market and who you know", "work experience catch-22s", "open days, careers fairs and free pens", "salary secrecy", "first-job reality versus the brochure"]

PIRATE_RULES = """You are the head writer for "Pirate Wei", a TikTok account for UK university students and recent graduates. Pirate Wei says out loud what everyone job hunting is thinking: he mocks the nonsense of the careers world, then tells the truth. You write one 7-slide carousel at a time. It is published without a human editor, so it must be right first time.

VOICE
- Dry, sarcastic, quick British humour. An older mate who has seen it all and is done pretending. Punch up at the SYSTEM (adverts, processes, buzzwords, hype), never down at students, and never at named people or named companies.
- Short sentences. Deadpan beats shouting. One clean joke per line. No exclamation marks.
- Plain modern British English. Do NOT write in pirate dialect: no "arr", "matey", "ye" or nautical puns. The only pirate thing about him is that he does not follow the rules of polite careers talk.
- No swearing and no crude words. "Rubbish" and "nonsense" are as strong as it gets.

BRITISH ENGLISH ONLY
- British spelling: organise, recognise, programme, colour, favourite, centre, behaviour, practise (verb) and practice (noun).
- UK terms: CV (never resume), university or uni (never college), graduate scheme, placement, internship, assessment centre, careers service, mate.

TRUTH AND SAFETY (most important)
- Opinion and satire only. No statistics, percentages, salaries, pay figures, dates, survey or study claims, and nothing presented as a researched fact or as news.
- Never name or hint at a real company, university, recruiter, public figure or any real person. Everyday tools are fine (LinkedIn, Excel, Zoom, Teams).
- Never mock people for who they are: nothing about nationality, race, religion, sex, gender, sexuality, age, disability, class or accent.
- Every slide ends on something TRUE and USEFUL. The rant is the hook, the truth is the point. Never tell readers to lie, cheat, give up, burn bridges or be rude to anyone.
- No legal, visa, tax or medical advice. No links, @mentions, hashtags or emojis inside slide text. Never use em dashes or en dashes.

CAROUSEL FORMAT (exact)
Slide 1 is the cover. Slides 2 to 6 are five lies or absurdities. Slide 7 is the closing slide.
- "topic": 3 to 8 words naming the topic.
- "tag": one or two words for the cover label, letters only, max 16 characters, e.g. "job adverts".
- "head": the cover headline as 2 to 4 SHORT LINES IN CAPITALS. Each line max 13 characters including spaces. Together they read as one blunt, funny claim. Wrap exactly ONE word or short phrase in <g></g> (shown in gold). Keep the <g> span inside a single line.
- "pill": cover sub-label that starts with "5 ", like "5 lies they keep telling" (max 24 characters if head has 4 lines, otherwise max 34).
- "hacks": exactly 5 items. Each item is three strings:
    1. the lie: the thing the careers world says, as a short phrase ending with a full stop, WITHOUT quotation marks (8 to 34 characters), e.g. "Competitive salary."
    2. the rant: one or two deadpan sentences on why it is nonsense (max 75 characters).
    3. the truth: what is actually going on and what to do about it, concrete and honest (max 70 characters).
  The five must be clearly different from each other.
- "out": three strings for the closing slide:
    1. a question that starts with "Which" and can be answered with a number from 1 to 5, e.g. "Which lie got you?" (max 26 characters)
    2. starts with "Save this " (max 30 characters)
    3. starts with "Send it to " (max 32 characters)
- "hook": the caption opener, one or two sentences in the same dry voice (max 140 characters, no emojis, no hashtags).
- "hashtags": 9 lowercase hashtags without the # sign, letters and digits only: about 5 broad UK graduate tags and 4 topic tags.

GOLD STANDARD EXAMPLE (match this quality, structure and length; do not reuse this topic)
{"topic":"What job adverts really mean","tag":"job adverts","head":["JOB ADVERTS","ARE <g>FICTION.</g>"],"pill":"5 lies they keep telling","hacks":[["Entry level.","Then it asks for years of experience. For a first job.","The list is a wish list. Meet most of it and apply."],["Competitive salary.","If it were competitive, it would be in the advert.","Ask for the range before the first interview."],["We are like a family.","Families do not usually have performance reviews.","Ask what a normal week looks like. Listen to the pause."],["Fast-paced environment.","A polite way of saying nobody has a plan.","Ask how priorities are set when everything is urgent."],["We will be in touch.","Sometimes they are. Sometimes the silence is the answer.","Chase once after a week, then keep applying elsewhere."]],"out":["Which lie got you?","Save this for your next advert","Send it to a mate job hunting"],"hook":"Job adverts are a creative writing exercise. Here is the translation.","hashtags":["ukgraduate","graduatejobs","ukstudents","jobhunting","careerhumour","jobadverts","jobsearchuk","graduatelife","recruitment"]}

BEFORE YOU ANSWER, CHECK YOUR OWN WORK
1. Count the characters of every line against its limit. Shorten anything over.
2. Is every spelling British? Is there any pirate dialect, swearing, number, statistic or named company or person? Remove it.
3. Is each joke aimed at the system and not at a group of people?
4. Does every truth line give the reader something honest they can do?
5. Are the five different from each other and from the already used topics?

Return ONLY the JSON object with exactly these keys: topic, tag, head, pill, hacks, out, hook, hashtags. No commentary, no markdown."""

PIRATE_REVIEW = """You are a strict British sub-editor and comedy editor. You are the last check before a satirical TikTok carousel for UK students and graduates is published with no human editor. The account mocks the nonsense of the careers world and then tells the truth.

Read the carousel JSON and fail it if ANY of these is true:
1. Any American spelling or term, pirate dialect, swearing, or any grammar or punctuation mistake.
2. It names or clearly points at a real company, university, public figure or real person.
3. A joke is aimed at people for who they are (nationality, race, religion, sex, gender, sexuality, age, disability, class, accent), or is cruel to students or job seekers.
4. Any statistic, percentage, pay figure, date, invented fact, anything presented as news, or legal, visa, tax or medical advice.
5. A truth line is false, unhelpful, dishonest, tells the reader to lie or be rude, or would backfire in a real UK job search.
6. It is not funny: the rant lines are bland, preachy, or the same joke five times.
7. The cover headline does not read naturally as one phrase, or the closing question cannot be answered with a number from 1 to 5.
8. Anything that could embarrass a small UK careers company if it went viral.

Be strict but fair: do not fail it for style preferences.
Return ONLY JSON: {"verdict": "pass" or "fail", "problems": ["field name: what is wrong and how to fix it", ...]} with at most 6 problems (an empty list on pass)."""

ONLY_RULES = """You are the head writer for "The Only Wei", a TikTok account that gives UK university students and recent graduates one professional idea a day, each built on a real quote from a well-known person in business or public life. You write one 7-slide carousel at a time. It is published without a human editor, so it must be right first time.

HOW IT WORKS
- You are GIVEN the quote, the person and the source. They are already checked and are printed on the cover by the system. You never write, repeat, reword, shorten, extend or correct the quote, and you never write any other quotation.
- Slides 2 to 6 are five lessons: The Only Wei's OWN practical take on how a student or graduate can use the idea in the quote. Slide 7 is the closing slide.

VOICE
- Calm, sharp, grown-up. A mentor a few years ahead who respects the reader. Confident, never preachy, never hype. No hustle-culture slogans.
- Plain words, short sentences, active verbs.

BRITISH ENGLISH ONLY (your own text; the quote stays as it was said)
- British spelling: organise, prioritise, recognise, programme, colour, favourite, centre, behaviour, practise (verb) and practice (noun).
- UK terms: CV (never resume), university or uni (never college), graduate scheme, placement, internship, careers service.

TRUTH AND SAFETY (most important)
- NEVER put words in the person's mouth. Do not say what they "meant", "believe", "always say", "would tell you" or "did". Do not state any fact about their life, companies, wealth, habits or history. Do not mention the person at all in the lessons: the lessons are general advice that stands on its own.
- Do not praise or criticise the person, and nothing political.
- No statistics, percentages, salaries, pay figures, dates, study or survey claims, or anything presented as a researched fact.
- No promises ("guaranteed", "will get you hired"). Honest wording: "often", "can", "tends to".
- Advice must be honest and fair to employers. No legal, visa, tax, medical or investment advice.
- No links, @mentions, hashtags or emojis inside slide text. No quotation marks anywhere in your text. Never use em dashes or en dashes.

CAROUSEL FORMAT (exact)
- "topic": 3 to 8 words naming the idea, e.g. "Protecting your reputation at work".
- "pill": cover sub-label that starts with "5 ", like "5 ways to use this" (max 30 characters).
- "hacks": exactly 5 lessons. Each is three strings:
    1. headline: an instruction that starts with a verb and ends with a full stop (12 to 34 characters), e.g. "Keep small promises."
    2. why: one sentence saying why it matters (max 75 characters).
    3. action: one concrete thing to do this week, specific enough to copy (max 70 characters).
  The five lessons must be clearly different from each other and clearly follow from the idea in the quote.
- "out": three strings for the closing slide:
    1. a question that starts with "Which" and can be answered with a number from 1 to 5, e.g. "Which will you start with?" (max 26 characters)
    2. starts with "Save this " (max 30 characters)
    3. starts with "Send it to " (max 32 characters)
- "hook": the caption opener, one or two sentences on why this idea matters early in a career (max 140 characters, no emojis, no hashtags, no quotation marks, do not name the person).
- "hashtags": 9 lowercase hashtags without the # sign, letters and digits only: about 5 broad UK graduate and career tags and 4 topic tags. No hashtag may contain a person's name.

GOLD STANDARD EXAMPLE (for a quote about reputation taking years to build and minutes to ruin; match this quality and length; do not reuse it)
{"topic":"Protecting your reputation at work","pill":"5 ways to use this","hacks":[["Keep small promises.","Reputation is built from the little things people can rely on.","Say when you will reply, then reply by then."],["Own mistakes early.","A problem raised early is a fix. Raised late, it is a story.","Tell your manager the same day, with one idea to fix it."],["Write as if it gets forwarded.","Messages travel further than you expect.","Reread anything sharp once before you press send."],["Be the same in every room.","People compare notes more than you think.","Speak about absent colleagues as if they were present."],["Tidy your public profile.","Employers often look you up before they meet you.","Search your own name and fix the first page."]],"out":["Which will you start with?","Save this for your first job","Send it to a friend starting work"],"hook":"Your name walks into the room before you do. Here is how to look after it from day one.","hashtags":["ukgraduate","graduatejobs","ukstudents","careeradvice","firstjob","reputation","professionalism","worktips","careergrowth"]}

BEFORE YOU ANSWER, CHECK YOUR OWN WORK
1. Count the characters of every line against its limit. Shorten anything over.
2. Have you mentioned the person, quoted anything, or claimed what they meant? Remove it.
3. Is every spelling British? Any number, statistic or promise? Remove it.
4. Does each lesson start with a verb and give an action the reader can do this week?
5. Are the five lessons different from each other and from the already used topics?

Return ONLY the JSON object with exactly these keys: topic, pill, hacks, out, hook, hashtags. No commentary, no markdown."""

ONLY_REVIEW = """You are a strict British sub-editor and an experienced UK university careers adviser. You are the last check before a TikTok carousel for UK students and graduates is published with no human editor. Its cover shows a real, already-checked quote ("quote_on_cover"); the rest is the account's own advice.

Read the carousel JSON and fail it if ANY of these is true:
1. Outside "quote_on_cover", the text names the quoted person, contains any quotation, or claims what the person meant, believes, did or would say, or states any fact about their life or companies.
2. Any American spelling or term in the account's own text, or any grammar or punctuation mistake.
3. Any lesson is wrong, misleading, vague, unsafe, dishonest, unfair to employers, or would not work in the UK job market.
4. Any statistic, percentage, pay figure, date, invented fact, promise of results, political point, or legal, visa, tax, medical or investment advice.
5. The lessons do not clearly follow from the idea in the quote, or two lessons say nearly the same thing.
6. In any lesson the headline, the why line and the action do not belong together, or the action is not concrete.
7. The closing question cannot be answered with a number from 1 to 5.
8. Anything a careful editor at a UK careers service would not publish.

Be strict but fair: do not fail it for style preferences.
Return ONLY JSON: {"verdict": "pass" or "fail", "problems": ["field name: what is wrong and how to fix it", ...]} with at most 6 problems (an empty list on pass)."""

PROFILES = {
    "hacker": {"id": "hacker", "rules": RULES, "review": REVIEW, "areas": AREAS, "tag": "hackerwei", "follow": "Save this and follow for a new hack every day."},
    "pirate": {"id": "pirate", "rules": PIRATE_RULES, "review": PIRATE_REVIEW, "areas": PIRATE_AREAS, "tag": "piratewei", "follow": "Follow for a daily rant about the careers world."},
    "only":   {"id": "only", "rules": ONLY_RULES, "review": ONLY_REVIEW, "areas": [], "tag": "theonlywei", "follow": "Save this and follow for one idea a day."},
}

BANNED = [r"%", r"£", r"\$", r"€", r"\bper ?cent\b", r"\bguarantee", r"\bstud(y|ies) (show|found|suggest)", r"\bresearch (shows|found|suggests)",
          r"\bsurvey", r"\baccording to\b", r"\bstatistic", r"\b\d+ (in|out of) \d+\b", r"https?://", r"www\.", r"@\w", r"\blie\b", r"\bfake\b",
          r"\b(one|two|three|four|five|six|seven|eight|nine|ten) (in|out of) (two|three|four|five|six|seven|eight|nine|ten|every)\b",
          r"\b(half|most|majority) of (all )?(employers|recruiters|graduates|students|applicants|candidates)\b", r"\b\d{2,}\b"]
ALLOWED_NUMBERS = {"24", "10", "15", "30", "60"}   # times and durations that are advice, not statistics

UK_SPELL = {"organize": "organise", "organized": "organised", "organizing": "organising", "organization": "organisation",
    "summarize": "summarise", "summarized": "summarised", "prioritize": "prioritise", "prioritized": "prioritised",
    "recognize": "recognise", "recognized": "recognised", "realize": "realise", "realized": "realised", "emphasize": "emphasise",
    "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing", "specialize": "specialise", "specialized": "specialised",
    "personalize": "personalise", "personalized": "personalised", "customize": "customise", "customized": "customised",
    "optimize": "optimise", "optimized": "optimised", "memorize": "memorise", "apologize": "apologise", "finalize": "finalise",
    "maximize": "maximise", "minimize": "minimise", "utilize": "use", "visualize": "visualise", "familiarize": "familiarise",
    "color": "colour", "colors": "colours", "favor": "favour", "favorite": "favourite", "behavior": "behaviour", "honor": "honour",
    "center": "centre", "centers": "centres", "program": "programme", "programs": "programmes", "enroll": "enrol",
    "skillful": "skilful", "fulfill": "fulfil", "labor": "labour", "neighbor": "neighbour", "catalog": "catalogue", "dialog": "dialogue",
    "math": "maths", "résumé": "CV", "resumé": "CV", "judgment": "judgement", "traveling": "travelling", "canceled": "cancelled",
    "modeling": "modelling", "labeled": "labelled", "gray": "grey", "inquire": "enquire", "inquiry": "enquiry"}
US_TERMS = [r"\bresumes?\b", r"\bgpa\b", r"\bfreshm[ae]n\b", r"\bsophomores?\b", r"\bsemesters?\b", r"\bvacation\b", r"\bcollege\b",
            r"\bpaycheck\b", r"\b401k\b", r"\bzip code\b", r"\bhigh school\b", r"\bgrad school\b", r"\bmajor in\b", r"\bmom\b"]

def clean(t):
    t = str(t).replace("—", ", ").replace("–", " to ").replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"').replace("…", "...")
    def fix(m):
        w = m.group(0); r = UK_SPELL[w.lower()]
        return r.upper() if w.isupper() and len(w) > 1 else (r[0].upper() + r[1:] if w[0].isupper() else r)
    t = re.sub(r"\b(" + "|".join(map(re.escape, UK_SPELL)) + r")\b", fix, t, flags=re.I)
    t = re.sub(r"\b([Pp])ractice (saying|answering|your|the|with|out|each|it|on|in|for|until|before|aloud|this|that|these|a|an)\b", r"\1ractise \2", t)
    t = re.sub(r"\bPRACTICE (SAYING|ANSWERING|YOUR|THE|WITH|OUT|EACH|IT|ON|IN|FOR|UNTIL|BEFORE|ALOUD|THIS|THAT|THESE|A|AN)\b", r"PRACTISE \1", t)
    t = re.sub(r"\bstar method\b", "STAR method", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()

def words(t): return {w for w in re.findall(r"[a-z]{4,}", t.lower())}

def validate(sp, used):
    """Returns a list of problems (empty when the spec is acceptable)."""
    p = []
    if P["id"] != "hacker": sp["cmd"] = "run --post"                     # only Hacker Wei shows a terminal command
    if P["id"] == "only": sp["head"] = ["<g>QUOTE</g>"]                  # the cover is the quote itself
    if P["id"] == "pirate":
        sp["tag"] = re.sub(r"[^A-Za-z ]", "", clean(sp.get("tag", "careers")))[:18].strip() or "careers"
    need = {"topic": str, "cmd": str, "head": list, "pill": str, "hacks": list, "out": list, "hook": str, "hashtags": list}
    for k, typ in need.items():
        if not isinstance(sp.get(k), typ): p.append(f"missing or wrong type: {k}")
    if p: return p
    sp["topic"], sp["cmd"], sp["pill"], sp["hook"] = clean(sp["topic"]), clean(sp["cmd"]), clean(sp["pill"]), clean(sp["hook"])
    sp["head"] = [clean(x).upper().replace("<G>", "<g>").replace("</G>", "</g>") for x in sp["head"]]
    sp["out"] = [clean(x) for x in sp["out"]]
    if P["id"] != "only" and not (2 <= len(sp["head"]) <= 4): p.append("head must have 2 to 4 lines")
    for l in sp["head"]:
        if len(re.sub(r"</?g>", "", l)) > 13: p.append(f"head line too long (max 13 characters): {l}")
        if re.sub(r"</?g>", "", l) != re.sub(r"<[^>]*>", "", l) or l.count("<g>") != l.count("</g>"): p.append(f"bad tags in head line: {l}")
    if not re.fullmatch(r"[a-z]+( --?[a-z-]+){1,2}", sp["cmd"]) or len(sp["cmd"]) > 26: p.append("cmd must look like: verb --flag (max 26 characters)")
    lim = 24 if len(sp["head"]) == 4 else 34
    if len(sp["pill"]) > lim or not sp["pill"].startswith("5 "): p.append(f"pill must start with '5 ' and be max {lim} characters")
    if len(sp["hacks"]) != 5: p.append("hacks must have exactly 5 items")
    for i, h in enumerate(sp["hacks"]):
        if not (isinstance(h, list) and len(h) == 3 and all(isinstance(x, str) for x in h)):
            p.append(f"hack {i+1} must be a list of 3 strings"); continue
        h[:] = [clean(x) for x in h]
        for j, (name, mx) in enumerate((("headline", 36), ("why line", 80), ("action", 75))):
            if not (8 <= len(h[j]) <= mx): p.append(f"hack {i+1} {name} must be 8 to {mx} characters: {h[j]}")
        if not h[0].endswith((".", "?", "!")): h[0] += "."
    if len(sp["out"]) != 3: p.append("out must have 3 items")
    else:
        for x, mx in zip(sp["out"], (28, 32, 34)):
            if not (6 <= len(x) <= mx): p.append(f"out line must be 6 to {mx} characters: {x}")
    if not (20 <= len(sp["hook"]) <= 160): p.append("hook must be 20 to 160 characters")
    if sum(l.count("<g>") for l in sp["head"]) != 1: p.append("head must contain exactly one <g></g> span")
    for i, h in enumerate(sp["hacks"]):
        if isinstance(h, list) and len(h) == 3 and len({x.lower() for x in h}) < 3: p.append(f"hack {i+1} repeats itself")
    heads = [h[0].lower() for h in sp["hacks"] if isinstance(h, list) and h]
    if len(set(heads)) < len(heads): p.append("two hacks have the same headline")
    if len(sp["out"]) == 3:
        if not (sp["out"][0].startswith("Which ") and sp["out"][0].endswith("?")): p.append('out[0] must start with "Which " and end with "?"')
        if not sp["out"][1].startswith("Save this "): p.append('out[1] must start with "Save this "')
        if not sp["out"][2].startswith("Send it to "): p.append('out[2] must start with "Send it to "')
    tags = [re.sub(r"[^a-z0-9]", "", str(t).lower()) for t in sp["hashtags"]]
    tags = [t for i, t in enumerate(tags) if 3 <= len(t) <= 30 and t not in tags[:i] and t != P["tag"]][:9]
    if len(tags) < 5: p.append("need at least 5 valid hashtags")
    sp["hashtags"] = tags
    text = " ".join([sp["topic"], sp["pill"], sp["hook"], *sp["head"], *sp["out"], *[x for h in sp["hacks"] if isinstance(h, list) for x in h]])
    if re.search(r"[–—]", text): p.append("contains a dash character")
    if re.search(r"[^\x00-\x7f]", re.sub(r"</?g>", "", text)): p.append("slides and hook must use plain characters only (no emojis or symbols)")
    low = re.sub(r"</?g>", "", text).lower()
    for u in US_TERMS:
        m = re.search(u, low)
        if m: p.append(f"American term, use the UK term instead: '{m.group(0)}'")
    for b in BANNED:
        if P["id"] == "pirate" and b in (r"\blie\b", r"\bfake\b"): continue      # Pirate Wei is allowed to call a lie a lie
        for m in re.finditer(b, low):
            if m.group(0).strip() in ALLOWED_NUMBERS: continue
            p.append(f"banned content (statistics, money, promises, links or dishonest advice): '{m.group(0)}'")
    if P["id"] == "pirate" and re.search(r"\b(arr+|matey|ye|landlubbers?|scallywags?|booty|shiver)\b", low): p.append("too much pirate talk, write plain modern British English")
    mine = words(sp["topic"] + (" " + " ".join(sp["head"]) if P["id"] != "only" else ""))
    for u in used:
        other = words(u)
        if mine and other and len(mine & other) / min(len(mine), len(other)) >= 0.6:
            p.append(f"too similar to an already used topic: {u}"); break
    return p

class Gemini:
    """Small client: finds the current free Flash models, paces calls, and moves on when one is exhausted."""
    def __init__(self):
        self.key = os.environ["GEMINI_API_KEY"].strip()
        self.dead, self.main_calls, self.strikes = set(), 0, {}
        names = MODEL_IDS or self.discover() or FALLBACK_MODELS
        self.main = [n for n in names if "lite" not in n]
        self.lite = [n for n in names if "lite" in n]
        log("models: main", self.main, "lite", self.lite)

    def strike(self, model):
        """A model that is overloaded or timing out twice is left alone for the rest of this run (never the last one standing)."""
        self.strikes[model] = self.strikes.get(model, 0) + 1
        alive = [m for m in self.main + self.lite if m not in self.dead]
        if self.strikes[model] >= 2 and len(alive) > 2: self.dead.add(model)

    def discover(self):
        try:
            req = urllib.request.Request(URL + "?pageSize=200", headers={"x-goog-api-key": self.key})
            with urllib.request.urlopen(req, timeout=60) as r:
                models = json.loads(r.read().decode()).get("models", [])
        except Exception as e:
            log("could not list models:", repr(e)[:200]); return []
        out = []
        for m in models:
            n = m.get("name", "").split("/")[-1]
            if "generateContent" not in m.get("supportedGenerationMethods", []): continue
            if not re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-lite)?", n): continue
            out.append((float(re.search(r"gemini-(\d+(?:\.\d+)?)", n).group(1)), n))
        out.sort(reverse=True)
        return [n for _, n in out]

    def call(self, system, user, prefer_lite=False, temperature=0.9):
        body = json.dumps({"system_instruction": {"parts": [{"text": system}]},
                           "contents": [{"role": "user", "parts": [{"text": user}]}],
                           "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}).encode()
        last = "no model available"
        for round_no in range(3):                      # up to 3 passes over the models, waiting between passes
            main = self.main if self.main_calls < MAIN_BUDGET else []
            order = (self.lite + main[:2]) if prefer_lite else (main + self.lite)
            order = [m for m in order if m not in self.dead]
            if not order: break
            for model in order:
                is_main = "lite" not in model
                req = urllib.request.Request(f"{URL}/{model}:generateContent", data=body, method="POST", headers={
                    "x-goog-api-key": self.key, "Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=90) as r:
                        raw = r.read().decode(errors="replace")
                    if is_main: self.main_calls += 1
                    time.sleep(PACE_MAIN if is_main else PACE_LITE)
                    try:
                        txt = "".join(p.get("text", "") for p in json.loads(raw)["candidates"][0]["content"]["parts"])
                    except Exception as e:
                        raise ValueError(f"unexpected API response: {raw[:300]!r}") from e
                    m = re.search(r"\{.*\}", txt, re.S)
                    if not m: raise ValueError(f"no JSON object in the reply: {txt[:200]!r}")
                    try:
                        return json.loads(m.group(0)), model
                    except Exception as e:
                        raise ValueError(f"reply was not valid JSON: {txt[:300]!r}") from e
                except urllib.error.HTTPError as e:
                    msg = re.sub(r"\s+", " ", e.read().decode(errors="replace"))[:220]
                    last = f"{model}: HTTP {e.code} {msg}"
                    if e.code in (400, 403, 404, 429): self.dead.add(model)   # gone, not allowed, or out of free quota: skip for this run
                    else: self.strike(model)
                except Exception as e:
                    last = f"{model}: {e!r}"
                    self.strike(model)
                log("model failed:", last[:300])
                time.sleep(PACE_LITE)
            log(f"no model answered on pass {round_no + 1}, waiting before trying again")
            time.sleep(RETRY_WAIT)
        raise RuntimeError(f"all models failed, last error: {last[:300]}")

RETRY_WAIT = float(os.environ.get("RETRY_WAIT", "45"))
PACE_MAIN = float(os.environ.get("PACE_MAIN", "13"))   # seconds between calls, to stay under the per-minute free limits
PACE_LITE = float(os.environ.get("PACE_LITE", "5"))

def ask_ai(ai, used, area, feedback, previous):
    ask = "Already used topics (do not repeat or closely overlap):\n- " + "\n- ".join(used[-120:])
    if P["id"] == "only":
        ask += ("\n\nThe quote for this carousel (already checked, it goes on the cover exactly as written; do not repeat, reword or extend it):\n"
                + json.dumps(area, ensure_ascii=False) + "\n\nWrite the carousel around this quote.")
    else:
        ask += (f"\n\nWrite one new carousel in this area: {area}. Choose a specific angle within it that a UK student "
                "or graduate would recognise at once, not a general overview.")
        if NEWS:
            ask += ("\n\nThis week's UK headlines, ONLY to help you pick a timely angle. Do not mention, quote or describe any event, person, "
                    "company or figure from them, and do not present anything as news:\n- " + "\n- ".join(NEWS))
    if feedback:
        ask += ("\n\nYour previous attempt was rejected. Here it is:\n" + json.dumps(previous, ensure_ascii=False) +
                "\n\nReasons it was rejected. Fix every one, keep what was good, and return the full corrected JSON:\n- "
                + "\n- ".join(feedback[:12]))
    sp, model = ai.call(P["rules"], ask)
    log(f"draft from {model}")
    return sp

def review(ai, sp):
    """Second opinion from the AI acting as editor. Returns a list of problems (empty on pass)."""
    show = {k: sp[k] for k in ("topic", "head", "pill", "hacks", "out", "hook") if not (k == "head" and P["id"] == "only")}
    if sp.get("quote"): show["quote_on_cover"] = sp["quote"]
    v, model = ai.call(P["review"], "Carousel JSON to review:\n" + json.dumps(show, ensure_ascii=False), prefer_lite=True, temperature=0.1)
    probs = [clean(x) for x in v.get("problems", []) if isinstance(x, str)][:6]
    log(f"review by {model}: {v.get('verdict')}")
    if str(v.get("verdict", "")).lower() == "pass": return []
    return probs or ["the editor rejected it without giving reasons, improve clarity and accuracy"]

def render(sp, outdir):
    """Renders the 7 slides, returns layout problems."""
    spec = {k: sp[k] for k in ("cmd", "head", "pill", "hacks", "out", "tag", "quote") if k in sp}
    f = os.path.join(outdir, "spec.json"); json.dump([spec], open(f, "w"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "make_carousel.py"), f, outdir], capture_output=True, text=True,
                       env=dict(os.environ, THEME=P["id"], BRAND=P.get("brand", "")))
    if r.returncode != 0: raise RuntimeError("render failed: " + r.stderr[-400:])
    p = []
    for x in json.load(open(os.path.join(outdir, "layout.json"))):
        s = x["slide"]
        if s == 1 and P["id"] == "only" and x["bottom"] > 1215: p.append("the cover is too full, shorten the pill")
        if s == 1 and x["right"] > 1030: p.append("a cover headline line is too wide, use shorter words")
        if 2 <= s <= 6 and (x["bottom"] > 1195 or x["right"] > 1022): p.append(f"hack {s-1} has too much text, shorten its three lines")
        if s == 7 and (x["bottom"] > 815 or x["right"] > 1030): p.append("the closing question or its two lines are too long")
    return p

def caption(sp):
    lines = []
    if sp.get("quote"):
        q = sp["quote"]; lines += [f'"{q["text"]}" {q["who"]} ({q["source"]})', ""]
    lines += [sp["hook"], "", sp["pill"] + ":"] + [f"{i+1}. {h[0].rstrip('.')}" for i, h in enumerate(sp["hacks"])]
    lines += ["", sp["out"][0] + " Comment the number \U0001F447", P["follow"], "",
              " ".join("#" + t for t in sp["hashtags"] + [P["tag"]])]
    return "\n".join(lines)

def fetch_news():
    """A few current UK work and business headlines, used only to steer topic choice. Any failure just means no headlines."""
    out = []
    for feed in ("https://www.theguardian.com/money/work-and-careers/rss", "https://feeds.bbci.co.uk/news/business/rss.xml"):
        try:
            req = urllib.request.Request(feed, headers={"User-Agent": "Mozilla/5.0 (autopost topic picker)"})
            with urllib.request.urlopen(req, timeout=20) as r: xml = r.read().decode(errors="replace")
            titles = re.findall(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml, re.S)
            out += [clean(re.sub(r"<[^>]+>", "", t))[:140] for t in titles[:6]]
        except Exception as e:
            log("no headlines from", feed, repr(e)[:120])
    return out[:10]

NEWS = []

def run_account(acct, ai, src, dry, budget):
    """Writes up to MAX_PER_RUN carousels for one account. Returns False when the AI is unavailable (stop the whole run)."""
    global POSTS, TOPICS, P
    P = dict(PROFILES[acct["profile"]], brand=acct["name"].upper(),
             tag=re.sub(r"[^a-z0-9]", "", (acct.get("handle") or acct["name"]).lower()) or PROFILES[acct["profile"]]["tag"])
    POSTS, TOPICS = common.posts_dir(acct), common.topics_file(acct)
    os.makedirs(POSTS, exist_ok=True)
    ids = sorted({f.split("_")[0] for f in os.listdir(POSTS) if f.endswith("_caption.txt")})
    topics = json.load(open(TOPICS)) if os.path.exists(TOPICS) else {"used": []}
    want = need(acct)
    bank = []
    if P["id"] == "only":
        used_q = set(topics.get("quotes", []))
        bank = [q for q in json.load(open(os.path.join(ROOT, "quotes.json")))["quotes"] if q["text"] not in used_q]
        random.shuffle(bank)
        if len(bank) < want: log(f"::warning::{acct['name']}: the quote bank has {len(bank)} unused quotes left. Add more to quotes.json.")
        want = min(want, len(bank))
    log(f"== {acct['name']}: writing {want}")
    made = 0
    recent = topics.get("areas", [])[-6:]
    started = time.time()
    for _ in range(want):
        if time.time() - started > budget:
            log("time budget for this account used up, stopping here"); break
        feedback, ok, sp = [], None, None
        area = bank.pop() if P["id"] == "only" else random.choice([a for a in P["areas"] if a not in recent] or P["areas"])
        for attempt in range(1, ATTEMPTS + 1):
            if attempt > 1 and time.time() - started > budget: break
            try:
                sp = json.load(open(src)) if src else ask_ai(ai, topics["used"], area, feedback, sp)
                if P["id"] == "only": sp["quote"] = area if not src else sp.get("quote", area)
                probs = validate(sp, topics["used"])
                tmp = tempfile.mkdtemp()
                if not probs: probs = render(sp, tmp)
                if not probs and ai: probs = review(ai, sp)
            except RuntimeError as e:
                log(f"::warning::AI unavailable right now: {e}"); return False
            if not probs: ok = (sp, tmp); break
            log(f"attempt {attempt} rejected:", "; ".join(probs[:6])); feedback = probs
            if src: break
        if not ok:
            log("::warning::Could not produce an acceptable carousel this time."); continue
        sp, tmp = ok
        new = f"{(max(int(i) for i in ids) + 1 if ids else 1):03d}"
        log(f"accepted {acct['name']} carousel {new}: {sp['topic']}")
        if not dry:
            for i in range(1, 8): shutil.copy(os.path.join(tmp, "Post 1", f"{i}.jpg"), os.path.join(POSTS, f"{new}_{i}.jpg"))
            open(os.path.join(POSTS, f"{new}_caption.txt"), "w", encoding="utf8").write(caption(sp))
            topics["used"].append(sp["topic"])
            if P["id"] == "only": topics.setdefault("quotes", []).append(sp["quote"]["text"])
            else: topics.setdefault("areas", []).append(area)
            os.makedirs(os.path.dirname(TOPICS), exist_ok=True)
            json.dump(topics, open(TOPICS, "w"), indent=1)
        else:
            log(caption(sp)); log("slides in", os.path.join(tmp, "Post 1"))
        ids.append(new); made += 1
        if P["id"] != "only": recent = (recent + [area])[-6:]
    log(f"{acct['name']}: made {made}")
    return True

def need(acct):
    waiting = len([i for i in common.waiting(acct) if not i["vault"]])
    if os.environ.get("FORCE") == "1": return max(1, min(MAX_PER_RUN, TARGET - waiting))
    return min(MAX_PER_RUN, max(0, TARGET - waiting))

def main():
    global NEWS
    dry = "--dry-run" in sys.argv
    src = sys.argv[sys.argv.index("--from-file") + 1] if "--from-file" in sys.argv else None
    only = os.environ.get("ACCOUNT", "all").strip() or "all"
    accts = [a for a in common.accounts() if a.get("profile") in PROFILES and only in ("all", a["id"])]
    have_key = bool(src or os.environ.get("GEMINI_API_KEY", "").strip())
    total = sum(need(a) for a in accts) if have_key else 0
    if "--need" in sys.argv:
        print(total); return 0
    if not total:
        log("nothing to write"); return 0
    ai = None if src else Gemini()
    if ai: NEWS = fetch_news()
    accts.sort(key=lambda a: len(common.waiting(a)))          # the emptiest queue is served first
    for a in accts:
        if not run_account(a, ai, src, dry, TIME_BUDGET / len(accts)): break
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        log(f"::warning::generation skipped: {e}"); sys.exit(0)
