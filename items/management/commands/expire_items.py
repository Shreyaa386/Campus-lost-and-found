from django.core.management.base import BaseCommand
from django.utils import timezone
from items.models import Item, ItemStatusHistory


class Command(BaseCommand):
    help = 'Automatically marks unresolved reports past their expiration date as expired.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report expired items without updating their status in the database.'
        )

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options.get('dry_run', False)

        expired_items = Item.objects.filter(
            status=Item.STATUS_OPEN,
            expires_at__lte=now
        )

        total_count = expired_items.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"[DRY RUN] {total_count} open reports are eligible for expiration.")
            )
            for item in expired_items:
                self.stdout.write(f"  - Item #{item.pk}: '{item.title}' (expires_at: {item.expires_at})")
            return

        updated_count = 0
        for item in expired_items:
            old_status = item.status
            item.status = Item.STATUS_EXPIRED
            item.save(update_fields=['status', 'updated_at'])

            ItemStatusHistory.objects.create(
                item=item,
                changed_by=None,
                old_status=old_status,
                new_status=Item.STATUS_EXPIRED,
                remarks='Automatically expired by system expiration job.'
            )
            updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Successfully expired {updated_count} outdated reports.")
        )

