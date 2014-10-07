import time
import pygit2

from gitfs.merges import AcceptMine
from gitfs.worker.fetch import FetchWorker

from gitfs.events import (fetch, syncing, sync_done, writers, shutting_down,
                          remote_operation, push_successful)


class MergeWorker(FetchWorker):
    def __init__(self, author_name, author_email, commiter_name,
                 commiter_email, strategy=None, *args, **kwargs):
        super(MergeWorker, self).__init__(*args, **kwargs)

        self.author = (author_name, author_email)
        self.commiter = (commiter_name, commiter_email)

        strategy = strategy or AcceptMine(self.repository, author=self.author,
                                          commiter=self.commiter,
                                          repo_path=self.repo_path)
        self.strategy = strategy

    def run(self):
        commits = []

        while True:
            if shutting_down.is_set():
                break

            try:
                job = self.merge_queue.get(timeout=self.timeout, block=True)
                print job, time.time()
                if job['type'] == 'commit':
                    commits.append(job)
                print "ceva treaba boss?"
            except:
                print "idle", time.time()
                commits = self.on_idle(commits)

    def on_idle(self, commits):
        """
        On idle, we have 4 cases:
        1. We have to commit and also need to merge some commits from remote.
        In this case, we commit and announce ourself for merging
        2. We are behind from remote, so we announce for merging
        3. We only need to commit
        4. We announced for merging and nobody is writing in this momement.
        In this case we are safe to merge and push.
        """

        if commits:
            self.commit(commits)
            commits = []
            syncing.set()

        if writers == 0:
            self.sync()

        return commits

    def merge(self):
        self.strategy(self.branch, self.branch, self.upstream)
        self.repository.commits.update()
        self.repository.ignore.update()

    def sync(self):
        need_to_push = self.repository.ahead(self.upstream, self.branch)
        sync_done.clear()

        if self.repository.behind:
            self.merge()
            need_to_push = True

        if need_to_push:
            try:
                with remote_operation:
                    print "start pushing", time.time()
                    self.repository.push(self.upstream, self.branch)
                    print "push done", time.time()
                    self.repository.behind = False
                syncing.clear()
                sync_done.set()
                push_successful.set()
            except Exception as e:
                print "push failed", time.time()
                print e
                push_successful.clear()
                fetch.set()

    def commit(self, jobs):
        if len(jobs) == 1:
            message = jobs[0]['params']['message']
        else:
            updates = set([])
            for job in jobs:
                updates = updates | set(job['params']['add'])
                updates = updates | set(job['params']['remove'])

            message = "Update %s items" % len(updates)

        print "commiting %s" % message
        self.repository.commit(message, self.author, self.commiter)
        self.repository.commits.update()
        self.repository.checkout_head(strategy=pygit2.GIT_CHECKOUT_FORCE)
