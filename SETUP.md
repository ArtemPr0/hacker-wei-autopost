# Hacker Wei autopost: one-time setup (about 45 minutes)

After this, one carousel is posted every day with nothing for you to approve. It is free: GitHub Actions runs the job and the Instagram API publishes it.

Queue: 10 carousels are ready (posts/001 to posts/010), about 10 days of content.

## 1. Check the account
Hacker Wei must be an Instagram Creator or Business account. You said it is a creator account, so you are fine.

## 2. Get an Instagram token and ID (Meta)
Menu names change, so aim for the result: a token for the Hacker Wei account with the permissions instagram_business_basic and instagram_business_content_publish, and the account's numeric ID.
1. Go to developers.facebook.com, log in and create an app (choose the Instagram use case, "Instagram API with Instagram login").
2. In the app, open Instagram > API setup with Instagram login, add the Hacker Wei account and log in as it.
3. Generate the access token. Copy it and the Instagram account ID shown beside it.
4. Leave the app in development mode. Because it is your own account, no app review is needed.

## 3. Put the folder on GitHub
1. Create a new PUBLIC repository (public is needed so Instagram can fetch the images).
2. Upload everything in this folder, including the hidden .github folder (GitHub Desktop or git is easier than drag and drop for that).

## 4. Add secrets
Repository Settings > Secrets and variables > Actions > New repository secret:
- IG_USER_ID: the account ID
- IG_ACCESS_TOKEN: the token
- GH_PAT (for the automatic token refresh): a fine-grained personal access token limited to this repository with "Secrets: Read and write"

Also check Settings > Actions > General that workflows are allowed to run.

## 5. Run it once
Actions tab > Post next carousel > Run workflow. This publishes posts/001 live straight away, as a test. After that it runs by itself at 17:30 UTC every day.

## What you get without doing anything
- GitHub emails you only when a run fails. Silence means it worked.
- The job also fails on purpose when 2 or fewer posts are left, so you get a "refill the queue" email.
- The token refreshes on the 1st and 15th of each month (Instagram tokens last 60 days).

## Honest notes
- I tested the script against a fake Instagram API (tools/mock_test.py), not the real one, so the first live run is the real test. If it errors, the message is in the Actions log.
- Instagram API menus and rules change. If a step looks different, tell me what you see.
- The queue ends after 10 posts. To refill, add folders 011, 012 and so on, each with 7 slide images (1.jpg to 7.jpg) and a caption.txt, or ask me for the next batch. Auto-writing new posts would need a paid AI API key, so I left that out to keep this free.
